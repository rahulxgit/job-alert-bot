"""Crawl4AI-based job discovery from configured public job-board roots.

This source complements the existing specialized sources. It starts from a
small, explicit set of public career/job-board roots, uses Crawl4AI deep
crawling to discover links, filters likely individual job pages, then
extracts each job page into the existing JobListing contract.

The implementation is intentionally bounded: max seed pages, max crawled
pages, max crawl depth, max accepted job pages, and per-page timeout are all
configurable. It does not replace LinkedIn/Google/Naukri/etc. and does not
call Firecrawl directly; generic_crawler remains the provider fallback layer
for known URLs.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
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
_JOB_PATH_MARKERS = (
    "/job/", "/jobs/", "/jobs/view/", "/vacancy/", "/position/", "/internship/",
)
_JOB_TEXT_SIGNALS = (
    "requirements", "qualifications", "responsibilities", "experience",
    "what you'll do", "what you will do", "apply", "skills", "education",
)


def _normalize_url(url: str) -> str:
    """Return a stable HTTPS/HTTP URL without common tracking parameters."""
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
    return host in {d.lower().removeprefix("www.") for d in config.CRAWL4AI_DISCOVERY_ALLOWED_DOMAINS}


def _looks_job_url(url: str, title: str = "") -> bool:
    normalized = _normalize_url(url)
    if not normalized or not _allowed_host(normalized):
        return False

    low = normalized.lower()
    title_low = (title or "").lower()

    if any(marker in low for marker in _AGGREGATE_MARKERS):
        return False
    if any(marker in low for marker in _JOB_PATH_MARKERS):
        return True

    # Some boards use opaque IDs/slugs without a conventional /job/ segment.
    # Require a meaningful title to reduce false positives.
    job_title_signal = any(
        token in title_low
        for token in ("software engineer", "developer", "sde", "frontend", "backend", "full stack", "intern")
    )
    return job_title_signal and len(urlparse(normalized).path.strip("/").split("/")) >= 2


def _extract_title(markdown: str, fallback: str) -> str:
    for line in (markdown or "").splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if 3 <= len(cleaned) <= 160:
            return cleaned
    return fallback or "Software Engineer"


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
    allowed = [d.lower().removeprefix("www.") for d in config.CRAWL4AI_DISCOVERY_ALLOWED_DOMAINS]
    patterns = [f"https://{re.escape(domain)}/*" for domain in allowed] + [
        f"https://www.{re.escape(domain)}/*" for domain in allowed
    ]
    filter_chain = FilterChain([URLPatternFilter(patterns=patterns)])
    scorer = KeywordRelevanceScorer(
        keywords=[
            "software engineer", "software developer", "sde", "frontend", "backend",
            "full stack", "react", "node", "javascript", "graduate", "fresher", "junior",
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


async def _discover() -> list[JobListing]:
    seeds = [
        seed for seed in config.CRAWL4AI_DISCOVERY_SEED_URLS[: config.CRAWL4AI_DISCOVERY_MAX_SEEDS]
        if _allowed_host(seed)
    ]
    if not seeds:
        return []

    run_config = CrawlerRunConfig(
        deep_crawl_strategy=_strategy(),
        stream=True,
        page_timeout=config.CRAWL4AI_DISCOVERY_TIMEOUT * 1000,
        preserve_https_for_internal_links=True,
    )

    rows: list[JobListing] = []
    seen: set[str] = set()

    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        for seed in seeds:
            try:
                results = await crawler.arun(url=seed, config=run_config)
                async for result in results:
                    url = _normalize_url(getattr(result, "url", "") or seed)
                    if not url or url in seen or not _allowed_host(url):
                        continue
                    seen.add(url)

                    markdown_obj = getattr(result, "markdown", "") or ""
                    markdown = getattr(markdown_obj, "raw_markdown", markdown_obj)
                    markdown = str(markdown).strip()
                    metadata = getattr(result, "metadata", {}) or {}
                    title = str(metadata.get("title") or "") if isinstance(metadata, dict) else ""

                    if _looks_job_url(url, title) and _looks_like_job_text(markdown):
                        rows.append(_to_listing(url, markdown, title))
                        log.info("[Crawl4AI] Discovered job: %s", url)
                        if len(rows) >= config.CRAWL4AI_DISCOVERY_MAX_DETAIL_PAGES:
                            return rows
            except Exception as exc:
                log.warning("[Crawl4AI] Discovery failed for seed %s: %s", seed, exc)

    return rows


def discover_job_listings() -> list[JobListing]:
    """Run bounded asynchronous discovery from the synchronous source API."""
    try:
        return asyncio.run(_discover())
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
