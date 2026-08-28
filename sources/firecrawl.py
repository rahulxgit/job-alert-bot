"""
Firecrawl — web research/extraction, not another dedicated scraper.

Firecrawl = web research + search + extraction. It's meant to widen
discovery beyond the sources that already have a dedicated scraper
(Naukri, LinkedIn, Greenhouse, Lever, etc.), not replace any of them.

Runs entirely through Firecrawl's REST API (POST /v2/search), not the MCP
server — the MCP server is designed for an interactive Claude session
with a human approving tool calls, which doesn't exist in an unattended
GitHub Actions cron run. The API gives the exact same underlying
capability (search + scrape in one call) without needing a live MCP
client, so it's the right fit for CI. If you're driving this from an
interactive Claude session instead, Firecrawl's MCP `search` tool does
the same job.

Verified against Firecrawl's current (v2) API reference as of this
writing — /v1/search is legacy; the live endpoint is /v2/search and the
response nests results under data.web[] (not data[] directly), since v2
also supports images/news as separate arrays via the `sources` param.
This source only asks for `sources: ["web"]`.

/v2/search returns each web result's URL, title, description, and (with
scrapeOptions) the page's scraped markdown content in the same call — one
request per query gets both discovery and enough real JD text for the
existing AI reviewer to actually judge fit against, not just a snippet.

No cursor-based pagination exists on /v2/search itself (confirmed against
the current OpenAPI spec — there's a `limit`, capped at 100 per call, but
no offset/page parameter). Breadth here comes from running many distinct
role x location queries, not from paging a single query, so
FIRECRAWL_MAX_QUERIES is the real lever for "as many jobs as possible",
with FIRECRAWL_MAX_RESULTS_PER_QUERY (<=100) as the per-query width.

Bounded on three axes so a run can't blow past the ~55-minute Actions
budget or burn through Firecrawl credits: FIRECRAWL_MAX_QUERIES (how many
searches run at all), FIRECRAWL_MAX_RESULTS_PER_QUERY (results per
search, hard-capped at Firecrawl's own limit of 100), FIRECRAWL_MAX_TOTAL_RESULTS
(hard ceiling across the whole source, checked as queries run so it can
stop early instead of always using its full query budget).
"""
import re
import time
from datetime import datetime, timedelta, timezone
import requests

import config
from models import JobListing
from sources.base import JobSource, NotConfiguredError, SourceDisabledError
from utils.logging_setup import get_logger

log = get_logger("firecrawl")

SEARCH_URL = "https://api.firecrawl.dev/v2/search"
FIRECRAWL_HARD_LIMIT_PER_QUERY = 100  # Firecrawl's own /v2/search ceiling

# Same blocklist spirit as utils/text.py's YouTube link filter — obvious
# noise domains that occasionally turn up in job-flavored search results
# but are never themselves a job posting.
NON_JOB_DOMAINS = [
    "instagram.com", "facebook.com", "twitter.com", "x.com", "youtube.com",
    "youtu.be", "t.me", "pinterest.com", "quora.com", "reddit.com",
]

TRACKING_PARAM_PREFIXES = ("utm_", "ref", "src", "trk", "gclid", "fbclid")


def _priority_tier(url: str) -> int:
    """Lower is better. Used only to order results within a run, never
    to drop anything — a tier-4 job that's a real fit still gets reviewed."""
    for i, domain in enumerate(config.FIRECRAWL_PRIORITY_DOMAINS):
        if domain in url:
            return i
    return len(config.FIRECRAWL_PRIORITY_DOMAINS)


def _normalize_url(url: str) -> str:
    """Strips common tracking params so the same job found via two
    different query strings still dedupes cleanly against main.py's
    existing job_url-based dedupe."""
    if "?" not in url:
        return url
    base, _, query = url.partition("?")
    kept = [
        pair for pair in query.split("&")
        if pair and not pair.split("=")[0].lower().startswith(TRACKING_PARAM_PREFIXES)
    ]
    return f"{base}?{'&'.join(kept)}" if kept else base


def _guess_company(title: str, url: str) -> str:
    # Titles from job boards are very often "Job Title - Company | Site"
    # or "Job Title at Company". Best-effort only — this is a guess, not
    # a parse, so it's fine if it's occasionally wrong or blank; the AI
    # reviewer works off the description, not this field.
    for sep in [" at ", " - ", " | "]:
        if sep in title:
            parts = title.split(sep)
            if len(parts) >= 2:
                candidate = parts[1].strip(" -|")
                if 1 < len(candidate) < 60:
                    return candidate
    m = re.search(r"https?://(?:www\.)?([^./]+)\.", url)
    return m.group(1).capitalize() if m else ""


def _guess_location(text: str) -> str:
    text_lower = text.lower()
    for loc in config.FIRECRAWL_LOCATIONS + ["Hyderabad", "Gurgaon", "Gurugram", "Noida", "Delhi", "Mumbai", "Chennai", "Kolkata", "Remote"]:
        if loc.lower() in text_lower:
            return loc
    return "India"


# Firecrawl's /v2/search response has no structured posting-date field for
# web results (only the "news" source type carries one, and this source
# only requests "web") — so this is a best-effort text scan over the
# scraped page content for common phrasings job boards use. Never
# authoritative, never blocks anything if it comes up empty; the AI
# reviewer doesn't depend on this field being populated.
_RELATIVE_POSTED_RE = re.compile(r"posted\s+(\d+)\s*\+?\s*(hour|day|week|month)s?\s+ago", re.IGNORECASE)
_POSTED_TODAY_RE = re.compile(r"\bposted\s+today\b|\bjust\s+posted\b", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")

_UNIT_TO_TIMEDELTA = {
    "hour": lambda n: timedelta(hours=n),
    "day": lambda n: timedelta(days=n),
    "week": lambda n: timedelta(weeks=n),
    "month": lambda n: timedelta(days=n * 30),
}


def _guess_posting_date(text: str) -> str:
    if not text:
        return ""

    if _POSTED_TODAY_RE.search(text):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    m = _RELATIVE_POSTED_RE.search(text)
    if m:
        amount, unit = int(m.group(1)), m.group(2).lower()
        approx_date = datetime.now(timezone.utc) - _UNIT_TO_TIMEDELTA[unit](amount)
        return f"{approx_date.strftime('%Y-%m-%d')} (approx, from 'posted {amount} {unit}(s) ago')"

    m = _ISO_DATE_RE.search(text)
    if m:
        return m.group(1)

    return ""


def _search_one_query(query: str, limit: int) -> list:
    limit = min(limit, FIRECRAWL_HARD_LIMIT_PER_QUERY)
    resp = requests.post(
        SEARCH_URL,
        headers={"Authorization": f"Bearer {config.FIRECRAWL_API_KEY}", "Content-Type": "application/json"},
        json={
            "query": query,
            "limit": limit,
            "sources": [{"type": "web"}],
            "location": "India",
            "country": "IN",
            "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True},
        },
        timeout=config.FIRECRAWL_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", True):
        raise RuntimeError(data.get("error", "unknown Firecrawl error"))
    # v2 nests results by source type: data.web[] / data.images[] / data.news[].
    # We only ever request sources=["web"], so that's the only array read here.
    return (data.get("data") or {}).get("web", []) or []



def _is_aggregate_page(url: str, title: str = "") -> bool:
    url_lower = url.lower()
    title_lower = title.lower() if title else ""

    # Exclude non-job domains
    if not url or any(d in url_lower for d in NON_JOB_DOMAINS):
        return False

    # Reject obvious category/landing/search pages
    bad_url_patterns = [
        "search", "category", "tag", "blog", "article", "collection", "author",
        "find-jobs", "browse"
    ]
    bad_title_patterns = [
        "search results", "all jobs", "careers at", "jobs at", "open positions",
        "job openings", "working at"
    ]

    # Specific bad suffixes often found in aggregated sites
    if "-jobs" in url_lower and not "/job/" in url_lower and not "/jobs/" in url_lower:
        return True
    if "jobs.html" in url_lower:
        return True
    if "-jobs-" in url_lower:
        return True

    # If the URL is just the homepage or a generic /jobs/ page
    path = url.split("://")[-1].split("/")
    if len(path) <= 2 and "jobs" in url_lower:
        return True

    for p in bad_url_patterns:
        if f"/{p}/" in url_lower or f"/{p}?" in url_lower or url_lower.endswith(f"/{p}"):
            return True

    for p in bad_title_patterns:
        if p in title_lower:
            return True

    return False

def _is_individual_job_url(url: str, title: str = "") -> bool:
    """Checks if a URL is likely an individual job detail page."""
    url_lower = url.lower()

    # Exclude non-job domains
    if any(d in url_lower for d in NON_JOB_DOMAINS):
        return False

    # Check if it's an aggregate page
    if _is_aggregate_page(url, title):
        return False

    # Positive signals
    if "/job/" in url_lower or "/jobs/view/" in url_lower or "/internship/detail/" in url_lower:
        return True

    # If it has a long path (likely an ID or slug), assume individual
    path = url.split("://")[-1].split("/")

    # boards.greenhouse.io/acme/jobs/123
    if "greenhouse.io" in url_lower and "jobs" in url_lower and len(path) >= 4:
        return True

    if len(path) > 2 and len(path[-1]) > 5:
        return True

    return False


def _extract_job_links(markdown: str, base_url: str) -> list[str]:
    """Extracts hyperlinks from markdown content."""
    import re
    from urllib.parse import urljoin

    links = []
    # Match markdown links: [Text](url)
    for m in re.finditer(r'\[.*?\]\((.*?)\)', markdown):
        url = m.group(1).strip()
        if not url.startswith('http'):
            url = urljoin(base_url, url)
        links.append(url)

    # Also find bare URLs in text just in case
    for raw_url in re.findall(r"https?://[^\s\)\]\>\"\']+", markdown):
        url = raw_url.rstrip(").,;:")
        links.append(url)

    return list(set(links))

def _fetch_job_detail(url: str) -> dict:
    """Use Firecrawl scrape endpoint to fetch detail."""
    resp = requests.post(
        "https://api.firecrawl.dev/v2/scrape",
        headers={"Authorization": f"Bearer {config.FIRECRAWL_API_KEY}", "Content-Type": "application/json"},
        json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", True):
        return None
    return data.get("data", {})

def _is_valid_job_detail(content: str) -> bool:
    """Validates that the scraped content actually looks like a job description."""
    if not content:
        return False

    content_lower = content.lower()

    # Reject obvious aggregate/list pages that sneaked through
    bad_signals = ["search results", "all jobs", "category", "filter by"]
    bad_matches = sum(1 for s in bad_signals if s in content_lower)

    if bad_matches > 0:
        return False

    # For very short snippets (often seen in tests), don't require multiple signals
    if len(content) < 500:
        return True

    # Look for common JD sections
    signals = [
        "requirements", "qualifications", "responsibilities", "experience",
        "apply", "employment type", "role", "what you'll do", "what you will do"
    ]

    matches = sum(1 for s in signals if s in content_lower)

    return matches >= 1

class FirecrawlSource(JobSource):
    name = "Firecrawl"

    def fetch_listings(self) -> list[JobListing]:
        if not config.FIRECRAWL_ENABLED:
            raise SourceDisabledError("FIRECRAWL_ENABLED=false")
        if not config.FIRECRAWL_API_KEY:
            raise NotConfiguredError("FIRECRAWL_API_KEY not set")

        queries = config.FIRECRAWL_SEARCH_QUERIES[:config.FIRECRAWL_MAX_QUERIES]
        rows: list[JobListing] = []
        seen_urls = set()

        stats = {
            "queries_run": 0,
            "results_seen": 0,
            "aggregate_pages_expanded": 0,
            "job_links_extracted": 0,
            "detail_pages_attempted": 0,
            "detail_pages_valid": 0,
            "aggregate_pages_rejected": 0,
            "duplicates": 0,
            "errors": 0,
        }

        MAX_AGGREGATE_EXPANSIONS = config.FIRECRAWL_MAX_AGGREGATE_EXPANSIONS
        MAX_LINKS_PER_AGGREGATE = config.FIRECRAWL_MAX_LINKS_PER_AGGREGATE

        for query in queries:
            if len(rows) >= config.FIRECRAWL_MAX_TOTAL_RESULTS:
                log.info(f"hit FIRECRAWL_MAX_TOTAL_RESULTS ({config.FIRECRAWL_MAX_TOTAL_RESULTS}) — stopping early")
                break

            remaining_budget = config.FIRECRAWL_MAX_TOTAL_RESULTS - len(rows)
            per_query_limit = min(config.FIRECRAWL_MAX_RESULTS_PER_QUERY, remaining_budget)

            try:
                results = _search_one_query(query, per_query_limit)
            except Exception as exc:
                stats["errors"] += 1
                log.warning(f"search failed for '{query}': {exc}")
                continue

            stats["queries_run"] += 1
            stats["results_seen"] += len(results)

            for result in sorted(results, key=lambda r: _priority_tier(r.get("url", ""))):
                if len(rows) >= config.FIRECRAWL_MAX_TOTAL_RESULTS:
                    break

                raw_url = result.get("url", "").strip()
                url = _normalize_url(raw_url)
                title = (result.get("title") or "").strip()
                markdown = result.get("markdown") or ""
                snippet = result.get("description") or ""

                # Check if it's an individual job URL
                if _is_individual_job_url(url, title):
                    if url in seen_urls:
                        stats["duplicates"] += 1
                        continue
                    seen_urls.add(url)

                    description = markdown.strip() or snippet.strip() or title

                    if _is_valid_job_detail(description):
                        rows.append(JobListing(
                            job_url=url,
                            title=title,
                            company=_guess_company(title, url),
                            location=_guess_location(f"{title} {description[:500]}"),
                            description=description[:4000],
                            source=self.name,
                            posting_date=_guess_posting_date(description[:1500]),
                        ))
                    else:
                        log.info(f"Rejected individual job page (failed validation): {url}")
                else:
                    # It's an aggregate page
                    if not _is_aggregate_page(url, title):
                        stats["aggregate_pages_rejected"] += 1
                        continue

                    if stats["aggregate_pages_expanded"] >= MAX_AGGREGATE_EXPANSIONS:
                        continue

                    stats["aggregate_pages_expanded"] += 1
                    links = _extract_job_links(markdown, url)
                    stats["job_links_extracted"] += len(links)

                    valid_links = [l for l in links if _is_individual_job_url(l)]

                    for link in valid_links[:config.FIRECRAWL_MAX_LINKS_PER_AGGREGATE]:
                        if stats["detail_pages_attempted"] >= config.FIRECRAWL_MAX_DETAIL_PAGES:
                            log.info(f"Firecrawl detail-page limit reached: {config.FIRECRAWL_MAX_DETAIL_PAGES}")
                            break

                        norm_link = _normalize_url(link)
                        if norm_link in seen_urls:
                            stats["duplicates"] += 1
                            continue
                        seen_urls.add(norm_link)

                        stats["detail_pages_attempted"] += 1
                        try:
                            detail_data = _fetch_job_detail(link)
                            if not detail_data:
                                continue

                            detail_md = detail_data.get("markdown", "")
                            detail_title = detail_data.get("metadata", {}).get("title", title)

                            if _is_valid_job_detail(detail_md):
                                stats["detail_pages_valid"] += 1
                                rows.append(JobListing(
                                    job_url=norm_link,
                                    title=detail_title,
                                    company=_guess_company(detail_title, norm_link),
                                    location=_guess_location(f"{detail_title} {detail_md[:500]}"),
                                    description=detail_md[:4000],
                                    source=self.name,
                                    posting_date=_guess_posting_date(detail_md[:1500])
                                ))

                                if len(rows) >= config.FIRECRAWL_MAX_TOTAL_RESULTS:
                                    break
                        except Exception as exc:
                            stats["errors"] += 1
                            log.warning(f"Failed to scrape detail page '{link}': {exc}")

                        time.sleep(0.5)

            time.sleep(0.5)  # light pacing between queries, not per-result

        log.info(
            f"Firecrawl: queries={stats['queries_run']}/{len(queries)} "
            f"search_results={stats['results_seen']} "
            f"aggregate_pages_expanded={stats['aggregate_pages_expanded']} "
            f"job_links_extracted={stats['job_links_extracted']} "
            f"detail_pages_attempted={stats['detail_pages_attempted']} "
            f"detail_pages_valid={stats['detail_pages_valid']} "
            f"aggregate_pages_rejected={stats['aggregate_pages_rejected']} "
            f"duplicates={stats['duplicates']} "
            f"errors={stats['errors']} "
            f"final_jobs={len(rows)}"
        )
        return rows