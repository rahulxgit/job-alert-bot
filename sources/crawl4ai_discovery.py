"""Crawl4AI-based job discovery from configured public job-search pages.

This source complements the existing specialized sources. It starts from a
small, explicit set of public search/board URLs, uses Crawl4AI deep crawling
to discover links, filters likely individual job pages, then extracts each
job page into the existing JobListing contract.

The implementation is intentionally bounded: max seed pages, max discovered
links, max detail pages, maximum crawl depth, and per-page timeout are all
configurable. It does not replace LinkedIn/Google/Naukri/etc. and does not
call Firecrawl directly; generic_crawler remains the provider fallback layer
for known URLs.
"""
from __future__ import annotations

import asyncio
import re
from typing import Iterable
from urllib.parse import urljoin, urlparse

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from crawl4ai.deep_crawling import BestFirstCrawlingStrategy
from crawl4ai.deep_crawling.filters import FilterChain, URLPatternFilter

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
_JOB_SIGNALS = (
    "/job/", "/jobs/", "/jobs/view/", "/careers/", "/vacancy/", "/position/",
    "/internship/", "greenhouse.io", "lever.co", "myworkdayjobs.com",
)
_AGGREGATE_SIGNALS = (
    "search", "results", "category", "categories", "tag", "tags", "browse",
    "find-jobs", "jobs.html", "careers-at", "jobs-at",
)


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
    path = parsed.path or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}{query}"


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _looks_job_url(url: str, title: str = "") -> bool:
    normalized = _normalize_url(url)
    if not normalized:
        return False
    host = _host(normalized)
    if host in _NON_JOB_DOMAINS or any(host.endswith(f".{d}") for d in _NON_JOB_DOMAINS):
        return False
    low = normalized.lower()
    title_low = (title or "").lower()
    if any(signal in low for signal in _AGGREGATE_SIGNALS) and not any(signal in low for signal in ("/job/", "/jobs/view/")):
        return False
    if any(signal in low for signal in _JOB_SIGNALS):
        return True
    if any(token in title_low for token in ("software engineer", "developer", "sde", "frontend", "backend", "full stack", "intern")):
        return len(urlparse(normalized).path.strip("/").split("/")) >= 2
    return False


def _extract_links(markdown: str, base_url: str) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", markdown or ""):
        raw = match.group(1).strip()
        if raw.startswith(("http://", "https://")):
            links.append(raw)
        else:
            links.append(urljoin(base_url, raw))
    for raw in re.findall(r"https?://[^\s)\]}>\"']+", markdown or ""):
        links.append(raw.rstrip(".,;:"))
    return list(dict.fromkeys(_normalize_url(link) for link in links if _normalize_url(link)))


def _extract_title(markdown: str, fallback: str) -> str:
    for line in (markdown or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if 3 <= len(line) <= 160:
            return line
    return fallback or "Software Engineer"


def _guess_company(title: str, url: str) -> str:
    for sep in (" at ", " - ", " | "):
        if sep in title:
            candidate = title.split(sep, 1)[1].strip(" -|")
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
    low = markdown.lower()
    if len(markdown.strip()) < config.CRAWL4AI_DISCOVERY_MIN_DESCRIPTION_CHARS:
        return False
    signals = (
        "requirements", "qualifications", "responsibilities", "experience",
        "what you'll do", "what you will do", "apply", "skills",
    )
    return sum(1 for signal in signals if signal in low) >= 1


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


async def _discover() -> list[JobListing]:
    seeds = list(config.CRAWL4AI_DISCOVERY_SEED_URLS)[: config.CRAWL4AI_DISCOVERY_MAX_SEEDS]
    if not seeds:
        return []

    allowed_hosts = {_host(seed) for seed in seeds}
    pattern_parts = [re.escape(host) for host in allowed_hosts if host]
    url_filter = URLPatternFilter(patterns=[f"https?://({ '|'.join(pattern_parts) })/.*"] if pattern_parts else ["*"])
    filter_chain = FilterChain([url_filter])
    strategy = BestFirstCrawlingStrategy(
        max_depth=config.CRAWL4AI_DISCOVERY_MAX_DEPTH,
        max_pages=config.CRAWL4AI_DISCOVERY_MAX_PAGES,
        include_external=False,
        filter_chain=filter_chain,
        score_threshold=0.0,
    )
    run_config = CrawlerRunConfig(
        deep_crawl_strategy=strategy,
        stream=True,
        page_timeout=config.CRAWL4AI_DISCOVERY_TIMEOUT * 1000,
    )

    rows: list[JobListing] = []
    seen: set[str] = set()
    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        for seed in seeds:
            try:
                async for result in await crawler.arun(seed, config=run_config):
                    url = _normalize_url(getattr(result, "url", "") or seed)
                    markdown_obj = getattr(result, "markdown", "") or ""
                    markdown = getattr(markdown_obj, "raw_markdown", markdown_obj)
                    markdown = str(markdown).strip()
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    title = ""
                    metadata = getattr(result, "metadata", None)
                    if isinstance(metadata, dict):
                        title = str(metadata.get("title") or "")
                    if _looks_job_url(url, title) and _looks_like_job_text(markdown):
                        rows.append(_to_listing(url, markdown, title))
                        if len(rows) >= config.CRAWL4AI_DISCOVERY_MAX_DETAIL_PAGES:
                            return rows
            except Exception as exc:
                log.warning("[Crawl4AI] Discovery failed for seed %s: %s", seed, exc)
    return rows


def discover_job_listings() -> list[JobListing]:
    """Run the bounded asynchronous discovery crawler from the sync pipeline."""
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
