"""Crawl4AI-backed generic web crawler with a normalized result contract.

Crawl4AI is the primary provider for generic URL crawling. This module is
kept provider-only so callers can use normalized JobListing objects without
knowing which crawler produced them.
"""
import asyncio
from typing import Iterable

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

from models import JobListing
from sources.base import JobSource
from utils.logging_setup import get_logger

log = get_logger("crawl4ai")


class Crawl4AIError(RuntimeError):
    """Raised when Crawl4AI cannot return usable content."""


def _run(coro):
    """Run an async Crawl4AI operation from the synchronous source API."""
    try:
        return asyncio.run(coro)
    except RuntimeError as exc:
        # This normally means a caller already owns the event loop.
        raise Crawl4AIError(f"async crawler execution failed: {exc}") from exc


async def _crawl_url(url: str, timeout_ms: int) -> str:
    browser_config = BrowserConfig(headless=True)
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=timeout_ms,
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)
        if not result.success:
            raise Crawl4AIError(result.error_message or "crawl failed")
        markdown = getattr(result, "markdown", "") or ""
        if hasattr(markdown, "raw_markdown"):
            markdown = markdown.raw_markdown
        markdown = str(markdown).strip()
        if not markdown:
            raise Crawl4AIError("crawl returned empty content")
        return markdown


def scrape_url(url: str, *, title: str = "", company: str = "", location: str = "India", timeout_seconds: int = 30) -> JobListing:
    """Crawl one URL and normalize it into the existing JobListing contract."""
    if not url:
        raise Crawl4AIError("url is required")
    log.info(f"[Crawl4AI] Starting scrape: {url}")
    try:
        markdown = _run(_crawl_url(url, timeout_seconds * 1000))
    except Exception as exc:
        log.warning(f"[Crawl4AI] Failed: {exc}")
        raise Crawl4AIError(str(exc)) from exc

    listing = JobListing(
        job_url=url,
        title=title or url,
        company=company,
        location=location,
        description=markdown,
        source="Crawl4AI",
    )
    log.info(f"[Crawl4AI] Success: {url}")
    return listing


def crawl_urls(urls: Iterable[str], *, timeout_seconds: int = 30) -> list[JobListing]:
    """Crawl a bounded collection of URLs sequentially with clean resources."""
    rows = []
    for url in urls:
        try:
            rows.append(scrape_url(url, timeout_seconds=timeout_seconds))
        except Crawl4AIError:
            continue
    return rows


class Crawl4AISource(JobSource):
    """Optional generic URL source used by the provider layer."""

    name = "Crawl4AI"

    def __init__(self, urls: Iterable[str] | None = None, *, timeout_seconds: int = 30):
        self.urls = list(urls or [])
        self.timeout_seconds = timeout_seconds

    def fetch_listings(self) -> list[JobListing]:
        return crawl_urls(self.urls, timeout_seconds=self.timeout_seconds)
