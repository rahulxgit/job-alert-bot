"""Crawl4AI-based job discovery from configured public job-board roots."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai.deep_crawling import BestFirstCrawlingStrategy
from crawl4ai.deep_crawling.filters import FilterChain, URLPatternFilter
from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer

import config
from models import JobListing
from sources.base import JobSource
from utils.logging_setup import get_logger

log = get_logger("crawl4ai-discovery")

_NON_JOB_DOMAINS = {
    "instagram.com", "facebook.com", "twitter.com", "x.com", "youtube.com",
    "youtu.be", "t.me", "pinterest.com", "quora.com", "reddit.com",
}
_TRACKING_PREFIXES = ("utm_", "ref", "src", "trk", "gclid", "fbclid")
_AGGREGATE_MARKERS = (
    "/search", "/category", "/categories", "/tag", "/tags", "/browse",
    "/find-jobs", "jobs.html", "careers-at", "jobs-at",
)
_JOB_TEXT_SIGNALS = (
    "requirements", "qualifications", "responsibilities", "experience",
    "what you'll do", "what you will do", "apply", "skills", "education",
)
_DEFAULT_DISCOVERY_SEEDS = [
    "https://boards.greenhouse.io/", "https://jobs.lever.co/", "https://jobs.ashbyhq.com/",
    "https://www.naukri.com/", "https://internshala.com/jobs/", "https://wellfound.com/jobs",
    "https://www.linkedin.com/jobs/", "https://www.indeed.com/jobs", "https://www.ycombinator.com/jobs",
    "https://cutshort.io/jobs", "https://www.instahyre.com/", "https://www.hiringcafe.com/",
]
_DEFAULT_DISCOVERY_DOMAINS = [
    "boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com", "naukri.com", "www.naukri.com",
    "internshala.com", "www.internshala.com", "wellfound.com", "www.wellfound.com",
    "linkedin.com", "www.linkedin.com", "indeed.com", "www.indeed.com", "ycombinator.com",
    "www.ycombinator.com", "cutshort.io", "www.cutshort.io", "instahyre.com", "www.instahyre.com",
    "hiringcafe.com", "www.hiringcafe.com",
]

_ANTI_BOT_SIGNALS = (
    "checking your browser before accessing", "just a moment...", "attention required!",
    "please verify you are a human", "enable javascript and cookies to continue",
    "are you a robot?", "access denied - error code",
)


@dataclass(frozen=True)
class DiscoveryMetrics:
    seeds_attempted: int = 0
    seeds_succeeded: int = 0
    pages_seen: int = 0
    jobs_discovered: int = 0
    seed_failures: int = 0
    candidate_urls_found: int = 0
    anti_bot_seeds: int = 0


def _discovery_seeds() -> list[str]:
    configured = list(getattr(config, "CRAWL4AI_DISCOVERY_SEED_URLS", []) or [])
    return configured if len(configured) >= 4 else list(_DEFAULT_DISCOVERY_SEEDS)


def _discovery_domains() -> list[str]:
    configured = list(getattr(config, "CRAWL4AI_DISCOVERY_ALLOWED_DOMAINS", []) or [])
    return configured if len(configured) >= 4 else list(_DEFAULT_DISCOVERY_DOMAINS)


def _seed_concurrency() -> int:
    return max(1, int(getattr(config, "CRAWL4AI_DISCOVERY_SEED_CONCURRENCY", 3)))


def _healthcheck_enabled() -> bool:
    return str(getattr(config, "CRAWL4AI_DISCOVERY_HEALTHCHECK_ENABLED", "true")).lower() == "true"


def _healthcheck_url() -> str:
    return str(getattr(config, "CRAWL4AI_DISCOVERY_HEALTHCHECK_URL", "https://example.com/"))


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    kept = []
    for pair in parsed.query.split("&") if parsed.query else []:
        if not pair:
            continue
        key = pair.split("=", 1)[0].lower()
        if key.startswith(_TRACKING_PREFIXES):
            continue
        kept.append(pair)
    query = f"?{'&'.join(kept)}" if kept else ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}{query}"


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _allowed_host(url: str) -> bool:
    host = _host(url)
    if not host or host in _NON_JOB_DOMAINS:
        return False
    allowed = {d.lower().removeprefix("www.") for d in _discovery_domains()}
    return host in allowed


def _looks_job_url(url: str, title: str = "", text_signal: str = "") -> bool:
    normalized = _normalize_url(url)
    if not normalized or not _allowed_host(normalized):
        return False
    low = normalized.lower()
    title_low = (title or "").lower()
    text_low = (text_signal or "").lower()
    
    if any(marker in low for marker in _AGGREGATE_MARKERS):
        return False
        
    job_url_patterns = (
        r"/job-listings-[^/?]+", r"/job/[^/?]+", r"/jobs/[^/?]+", r"/jobs/view/[^/?]+",
        r"/vacancy/[^/?]+", r"/position/[^/?]+", r"/internship/[^/?]+", r"/viewjob(?:[/?]|$)",
        r"/careers/[^/?]+", r"/opportunities/[^/?]+"
    )
    if any(re.search(pattern, low) for pattern in job_url_patterns):
        return True
        
    job_title_signal = any(token in title_low for token in (
        "software engineer", "developer", "sde", "frontend", "backend", "full stack",
        "product engineer", "ai engineer", "ml engineer", "genai", "intern", "programmer", "engineer"
    ))
    
    job_text_signal = any(token in text_low for token in (
        "apply now", "view details", "software engineer", "developer", "sde"
    ))
    
    path_segments = [part for part in urlparse(normalized).path.strip("/").split("/") if part]
    
    if (job_title_signal or job_text_signal) and len(path_segments) >= 1:
        return True
        
    return False


def _extract_links(markdown: str, base_url: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", markdown or ""):
        raw = match.group(1).strip()
        found.append(raw if raw.startswith(("http://", "https://")) else urljoin(base_url, raw))
    found.extend(re.findall(r"https?://[^\s)\]}>\"']+", markdown or ""))
    normalized = []
    seen = set()
    for raw in found:
        clean = _normalize_url(raw.rstrip(".,;:"))
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)
    return normalized


_NAV_TITLE_BLOCKLIST = {
    "", "close", "menu", "about", "home", "sign in", "sign up", "log in", "login",
    "contact", "contact us", "careers", "jobs", "blog", "help", "faq", "search",
    "skip to content", "skip to main content", "toggle navigation", "toggle menu",
    "privacy policy", "terms of service", "cookie policy",
}

_MARKDOWN_LINK_PATTERN = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def _strip_markdown_link_syntax(text: str) -> str:
    """Unwrap [text](url) / ![alt](url) — including nested image-in-link
    markdown like [![logo](img-url)](page-url) — down to the visible text."""
    previous = None
    current = text
    while previous != current:
        previous = current
        current = _MARKDOWN_LINK_PATTERN.sub(r"\1", current)
    return current.strip()


def _extract_title(markdown: str, fallback: str) -> str:
    """Prefer the page's real <title> tag (passed in as fallback) over
    scanning markdown lines: the first non-empty markdown line on a job
    board page is frequently nav chrome (e.g. "Close", "[About](url)", a
    bare or nested-image link) rather than the actual job title, and those
    were being fed straight into the AI evaluator as fake candidates."""
    fallback_clean = _strip_markdown_link_syntax((fallback or "").strip())
    if fallback_clean and fallback_clean.lower() not in _NAV_TITLE_BLOCKLIST and 3 <= len(fallback_clean) <= 160:
        return fallback_clean

    for line in (markdown or "").splitlines():
        cleaned = _strip_markdown_link_syntax(line.strip().lstrip("#").strip())
        if cleaned.lower() in _NAV_TITLE_BLOCKLIST:
            continue
        if 3 <= len(cleaned) <= 160:
            return cleaned

    return fallback_clean or "Software Engineer"


def _guess_company(title: str, url: str) -> str:
    for separator in (" at ", " - ", " | "):
        if separator in title:
            candidate = title.split(separator, 1)[1].strip(" -|")
            if 1 < len(candidate) < 80:
                return candidate
    host = _host(url).split(".")
    return host[0].capitalize() if host else ""


def _guess_location(text: str) -> str:
    low = (text or "").lower()
    for location in config.CRAWL4AI_DISCOVERY_LOCATIONS:
        if location.lower() in low:
            return location
    return "India"


def _looks_like_job_text(markdown: str) -> bool:
    if not markdown:
        return False
    stripped = markdown.strip()
    if len(stripped) < config.CRAWL4AI_DISCOVERY_MIN_DESCRIPTION_CHARS:
        return False
    low = stripped.lower()
    return sum(1 for signal in _JOB_TEXT_SIGNALS if signal in low) >= 1


def _looks_like_anti_bot(markdown: str) -> bool:
    """Cheap heuristic: a Cloudflare/JS challenge or captcha page renders as a
    tiny amount of markdown carrying one of a handful of stock phrases. A real
    board root page is never this short."""
    stripped = (markdown or "").strip()
    if not stripped:
        return False
    low = stripped.lower()
    if len(stripped) < 400 and any(signal in low for signal in _ANTI_BOT_SIGNALS):
        return True
    return False


def _to_listing(url: str, markdown: str, seed_title: str = "") -> JobListing:
    title = _extract_title(markdown, seed_title)
    return JobListing(
        job_url=url,
        title=title,
        company=_guess_company(title, url),
        location=_guess_location(f"{title}\n{markdown[:1200]}"),
        description=markdown[: config.CRAWL4AI_DISCOVERY_MAX_DESCRIPTION_CHARS],
        source="Crawl4AI",
    )


def _strategy() -> BestFirstCrawlingStrategy:
    allowed = [d.lower().removeprefix("www.") for d in _discovery_domains()]
    patterns = [f"https://{domain}/*" for domain in allowed] + [f"https://www.{domain}/*" for domain in allowed]
    filter_chain = FilterChain([URLPatternFilter(patterns=patterns)])
    scorer = KeywordRelevanceScorer(
        keywords=[
            "software engineer", "software developer", "sde", "frontend", "backend",
            "full stack", "product engineer", "ai engineer", "ml engineer", "genai",
            "react", "node", "javascript", "graduate", "fresher", "junior", "intern",
        ],
        weight=0.8,
    )
    return BestFirstCrawlingStrategy(
        max_depth=config.CRAWL4AI_DISCOVERY_MAX_DEPTH,
        max_pages=config.CRAWL4AI_DISCOVERY_MAX_PAGES,
        include_external=False,
        filter_chain=filter_chain,
        url_scorer=scorer,
    )


def _extract_result_markdown(result) -> tuple[str, str, str, list]:
    url = _normalize_url(getattr(result, "url", "") or "")
    markdown_obj = getattr(result, "markdown", "") or ""
    markdown = getattr(markdown_obj, "raw_markdown", markdown_obj)
    markdown = str(markdown).strip()
    metadata = getattr(result, "metadata", {}) or {}
    title = str(metadata.get("title") or "") if isinstance(metadata, dict) else ""
    
    extracted_links = []
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", markdown):
        text = match.group(1).strip()
        link = match.group(2).strip()
        if link.startswith(("http://", "https://")):
            extracted_links.append({"href": link, "text": text})
        else:
            extracted_links.append({"href": urljoin(url, link), "text": text})
            
    result_links = getattr(result, "links", {})
    if isinstance(result_links, dict):
        for key in ["internal", "external"]:
            for link_obj in result_links.get(key, []):
                href = link_obj.get("href")
                text = link_obj.get("text")
                if href:
                    extracted_links.append({"href": href, "text": text})
                    
    return url, markdown, title, extracted_links


async def _crawl_seed(crawler, seed: str, run_config) -> tuple[str, list[JobListing], int, bool, int, bool]:
    discovered: list[JobListing] = []
    pages_seen = 0
    candidate_urls_found = 0
    anti_bot_detected = False
    try:
        results = await crawler.arun(url=seed, config=run_config)
        async for result in results:
            pages_seen += 1
            url, markdown, title, extracted_links = _extract_result_markdown(result)
            if not url or not _allowed_host(url):
                continue
            if _looks_like_anti_bot(markdown):
                anti_bot_detected = True
                continue
                
            if _looks_job_url(url, title):
                candidate_urls_found += 1
                if _looks_like_job_text(markdown):
                    discovered.append(_to_listing(url, markdown, title))
            
            for link_obj in extracted_links:
                href = _normalize_url(link_obj["href"])
                text = link_obj["text"]
                if href and _allowed_host(href) and _looks_job_url(href, title=text, text_signal=text):
                    candidate_urls_found += 1
                    
        return seed, discovered, pages_seen, True, candidate_urls_found, anti_bot_detected
    except Exception as exc:
        log.warning("[Crawl4AI] Discovery failed for seed %s: %s", seed, exc)
        return seed, [], pages_seen, False, 0, False


def _write_diagnostics(results: list[tuple[str, list[JobListing], int, bool, int, bool]], metrics: DiscoveryMetrics) -> None:
    path = Path("run-artifacts/crawl4ai-discovery-diagnostics.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    seeds = []
    for seed, rows, pages, request_success, candidate_urls_found, anti_bot_detected in results:
        if anti_bot_detected:
            seed_status = "BLOCKED"
        elif not request_success:
            seed_status = "FAILED"
        elif candidate_urls_found == 0:
            seed_status = "NO_CANDIDATES"
        elif not rows:
            seed_status = "CANDIDATES_NOT_VALIDATED"
        else:
            seed_status = "SUCCESS"
        seeds.append({
            "seed": seed,
            "pages_seen": pages,
            "candidate_urls_found": candidate_urls_found,
            "jobs_discovered": len(rows),
            "anti_bot_detected": anti_bot_detected,
            "request_success": request_success,
            "status": seed_status,
        })
    payload = {"metrics": asdict(metrics), "seeds": seeds}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def _discover() -> tuple[list[JobListing], DiscoveryMetrics]:
    max_seeds = max(1, int(getattr(config, "CRAWL4AI_DISCOVERY_MAX_SEEDS", 12)))
    seeds = [seed for seed in _discovery_seeds()[:max_seeds] if _allowed_host(seed)]
    if not seeds:
        return [], DiscoveryMetrics()

    run_config = CrawlerRunConfig(
        deep_crawl_strategy=_strategy(),
        stream=True,
        page_timeout=config.CRAWL4AI_DISCOVERY_TIMEOUT * 1000,
        preserve_https_for_internal_links=True,
    )

    unique_rows: dict[str, JobListing] = {}
    seed_successes = 0
    seed_failures = 0
    pages_seen = 0
    candidate_urls_found = 0
    anti_bot_seeds = 0
    semaphore = asyncio.Semaphore(_seed_concurrency())

    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        async def bounded_seed(seed: str):
            async with semaphore:
                return await _crawl_seed(crawler, seed, run_config)
        results = await asyncio.gather(*(bounded_seed(seed) for seed in seeds))

    for seed, rows, seed_pages_seen, request_success, seed_candidates, anti_bot_detected in results:
        pages_seen += seed_pages_seen
        seed_successes += int(request_success)
        seed_failures += int(not request_success)
        candidate_urls_found += seed_candidates
        anti_bot_seeds += int(anti_bot_detected)
        log.info(
            "[Crawl4AI] Seed %s: pages=%s candidates=%s jobs=%s anti_bot=%s request_success=%s",
            seed, seed_pages_seen, seed_candidates, len(rows), anti_bot_detected, request_success,
        )
        for row in rows:
            unique_rows.setdefault(row.job_url, row)
            if len(unique_rows) >= config.CRAWL4AI_DISCOVERY_MAX_DETAIL_PAGES:
                break
        if len(unique_rows) >= config.CRAWL4AI_DISCOVERY_MAX_DETAIL_PAGES:
            break

    rows = list(unique_rows.values())[: config.CRAWL4AI_DISCOVERY_MAX_DETAIL_PAGES]
    metrics = DiscoveryMetrics(
        seeds_attempted=len(seeds), seeds_succeeded=seed_successes, pages_seen=pages_seen,
        jobs_discovered=len(rows), seed_failures=seed_failures,
        candidate_urls_found=candidate_urls_found, anti_bot_seeds=anti_bot_seeds,
    )
    log.info(
        "[Crawl4AI] Discovery metrics: seeds=%s succeeded=%s failed=%s anti_bot=%s pages=%s candidates=%s jobs=%s",
        metrics.seeds_attempted, metrics.seeds_succeeded, metrics.seed_failures,
        metrics.anti_bot_seeds, metrics.pages_seen, metrics.candidate_urls_found, metrics.jobs_discovered,
    )
    _write_diagnostics(results, metrics)

    # Every seed failing outright (0 successes, at least one seed attempted) means
    # the crawler itself is broken (e.g. missing browser binaries, blocked network)
    # rather than "legitimately found nothing." Surface this as a real failure
    # instead of letting main.py record it as a healthy NO_RESULTS source, so it
    # shows up in the daily digest's source-health line and doesn't go unnoticed.
    if metrics.seeds_attempted > 0 and metrics.seeds_succeeded == 0:
        raise RuntimeError(
            f"Crawl4AI discovery: all {metrics.seeds_attempted} seeds failed — "
            "likely a browser/network problem, not a real 0-results day"
        )

    # A page can render fine (request_success=True) while every seed is a
    # Cloudflare/JS challenge or otherwise yields zero job-shaped candidate
    # URLs. That is exactly today's incident (12/12 "succeeded", 0 jobs) and
    # must not be reported as a healthy NO_RESULTS run — transport success is
    # not discovery success.
    if metrics.seeds_attempted > 0 and metrics.seeds_succeeded > 0 and metrics.candidate_urls_found == 0:
        if metrics.anti_bot_seeds > 0:
            raise RuntimeError(
                f"Crawl4AI discovery: {metrics.anti_bot_seeds}/{metrics.seeds_attempted} seeds "
                "returned anti-bot/challenge pages and zero real candidate URLs were found — "
                "treating as BLOCKED, not a real 0-results day"
            )
        raise RuntimeError(
            f"Crawl4AI discovery: {metrics.seeds_succeeded} seeds rendered successfully but "
            "zero job-shaped candidate URLs were extracted from any of them — likely selector/"
            "extraction drift, not a real 0-results day"
        )

    return rows, metrics


async def _healthcheck() -> str:
    url = _healthcheck_url()
    if not _healthcheck_enabled():
        log.info("[Crawl4AI] Health check disabled")
        return url
    run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=max(5000, config.CRAWL4AI_DISCOVERY_TIMEOUT * 1000))
    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.arun(url=url, config=run_config)
        if not result.success:
            raise RuntimeError(getattr(result, "error_message", "health check crawl failed"))
        markdown_obj = getattr(result, "markdown", "") or ""
        markdown = getattr(markdown_obj, "raw_markdown", markdown_obj)
        if len(str(markdown).strip()) < 50:
            raise RuntimeError("health check returned insufficient markdown")
    return url


def run_healthcheck() -> str:
    return asyncio.run(_healthcheck())


def discover_job_listings() -> list[JobListing]:
    try:
        rows, _ = asyncio.run(_discover())
        return rows
    except RuntimeError as exc:
        raise RuntimeError(f"Crawl4AI discovery execution failed: {exc}") from exc


class Crawl4AIDiscoverySource(JobSource):
    name = "Crawl4AI Discovery"

    def fetch_listings(self) -> list[JobListing]:
        if not config.CRAWL4AI_DISCOVERY_ENABLED:
            log.info("[Crawl4AI] Discovery disabled")
            return []
        rows = discover_job_listings()
        log.info("[Crawl4AI] Discovery returned %s job listings", len(rows))
        return rows