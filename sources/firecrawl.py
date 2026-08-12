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
from datetime import datetime, timedelta
import requests

import config
from models import JobListing
from sources.base import JobSource
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


def _is_job_like(url: str) -> bool:
    return bool(url) and not any(d in url.lower() for d in NON_JOB_DOMAINS)


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
        return datetime.utcnow().strftime("%Y-%m-%d")

    m = _RELATIVE_POSTED_RE.search(text)
    if m:
        amount, unit = int(m.group(1)), m.group(2).lower()
        approx_date = datetime.utcnow() - _UNIT_TO_TIMEDELTA[unit](amount)
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


class FirecrawlSource(JobSource):
    name = "Firecrawl"

    def fetch_listings(self) -> list[JobListing]:
        if not config.FIRECRAWL_ENABLED:
            log.info("disabled via FIRECRAWL_ENABLED=false — skipping")
            return []
        if not config.FIRECRAWL_API_KEY:
            log.info("FIRECRAWL_API_KEY not set — skipping")
            return []

        queries = config.FIRECRAWL_SEARCH_QUERIES[:config.FIRECRAWL_MAX_QUERIES]
        rows: list[JobListing] = []
        seen_urls = set()

        queries_run = 0
        results_seen = 0
        pages_with_content = 0
        rejected_non_job = 0
        duplicate_count = 0
        error_count = 0

        for query in queries:
            if len(rows) >= config.FIRECRAWL_MAX_TOTAL_RESULTS:
                log.info(f"hit FIRECRAWL_MAX_TOTAL_RESULTS ({config.FIRECRAWL_MAX_TOTAL_RESULTS}) — stopping early")
                break

            remaining_budget = config.FIRECRAWL_MAX_TOTAL_RESULTS - len(rows)
            per_query_limit = min(config.FIRECRAWL_MAX_RESULTS_PER_QUERY, remaining_budget)

            try:
                results = _search_one_query(query, per_query_limit)
            except Exception as exc:
                error_count += 1
                log.warning(f"search failed for '{query}': {exc}")
                continue

            queries_run += 1
            results_seen += len(results)

            for result in sorted(results, key=lambda r: _priority_tier(r.get("url", ""))):
                url = _normalize_url((result.get("url") or "").strip())
                if not _is_job_like(url):
                    rejected_non_job += 1
                    continue
                if url in seen_urls:
                    duplicate_count += 1
                    continue
                seen_urls.add(url)

                title = (result.get("title") or "").strip()
                if not title:
                    continue

                markdown = result.get("markdown") or ""
                snippet = result.get("description") or ""
                # Prefer the actually-scraped page content over the search
                # snippet — a full JD gives the existing AI reviewer far
                # more to judge fit against than a two-line snippet.
                description = markdown.strip() or snippet.strip() or title
                if markdown:
                    pages_with_content += 1

                rows.append(JobListing(
                    job_url=url,
                    title=title,
                    company=_guess_company(title, url),
                    location=_guess_location(f"{title} {description[:500]}"),
                    description=description[:4000],
                    source=self.name,
                    posting_date=_guess_posting_date(description[:1500]),
                ))

                if len(rows) >= config.FIRECRAWL_MAX_TOTAL_RESULTS:
                    break

            time.sleep(0.5)  # light pacing between queries, not per-result

        log.info(
            f"queries={queries_run}/{len(queries)} results={results_seen} "
            f"pages_with_content={pages_with_content} extracted={len(rows)} "
            f"rejected_non_job={rejected_non_job} duplicates={duplicate_count} errors={error_count}"
        )
        return rows
