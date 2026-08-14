"""
Crawl4AI-backed generic web crawler with a normalized result contract.

The batch path reuses one browser session and uses bounded concurrency so
browser startup overhead is paid once per batch instead of once per URL.
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
        raise Crawl4AIError(f"async crawler execution failed: {exc}") from exc


async def _crawl_url_with_crawler(crawler, url: str, timeout_ms: int) -> str:
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=timeout_ms,
    )
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


async def _crawl_batch(
    urls: list[str],
    *,
    timeout_ms: int,
    concurrency: int,
) -> dict[str, str | Exception]:
    """Crawl a batch with one browser session and bounded concurrency."""
    browser_config = BrowserConfig(headless=True)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: dict[str, str | Exception] = {}

    async with AsyncWebCrawler(config=browser_config) as crawler:
        async def worker(url: str) -> None:
            async with semaphore:
                try:
                    results[url] = await _crawl_url_with_crawler(crawler, url, timeout_ms)
                except Exception as exc:
                    results[url] = exc

        await asyncio.gather(*(worker(url) for url in urls))

    return results


def scrape_url(url: str, *, title: str = "", company: str = "", location: str = "India", timeout_seconds: int = 30) -> JobListing:
    """Crawl one URL and normalize it into the existing JobListing contract."""
    if not url:
        raise Crawl4AIError("url is required")
    log.info("[Crawl4AI] Starting scrape: %s", url)
    try:
        markdown = _run(_crawl_batch([url], timeout_ms=timeout_seconds * 1000, concurrency=1))[url]
        if isinstance(markdown, Exception):
            raise markdown
    except Exception as exc:
        log.warning("[Crawl4AI] Failed: %s", exc)
        raise Crawl4AIError(str(exc)) from exc

    listing = JobListing(
        job_url=url,
        title=title or url,
        company=company,
        location=location,
        description=markdown,
        source="Crawl4AI",
    )
    log.info("[Crawl4AI] Success: %s", url)
    return listing


def crawl_urls(
    urls: Iterable[str],
    *,
    timeout_seconds: int = 30,
    max_concurrency: int = 4,
) -> list[JobListing]:
    """Crawl a bounded collection using one browser session.

    Individual URL failures are isolated so one bad page never discards
    successful results from the same batch.
    """
    normalized_urls = [url for url in urls if url]
    if not normalized_urls:
        return []

    log.info(
        "[Crawl4AI] Batch scrape: %s URLs, concurrency=%s",
        len(normalized_urls),
        max(1, max_concurrency),
    )
    raw_results = _run(
        _crawl_batch(
            normalized_urls,
            timeout_ms=timeout_seconds * 1000,
            concurrency=max_concurrency,
        )
    )

    rows: list[JobListing] = []
    for url in normalized_urls:
        result = raw_results.get(url)
        if isinstance(result, Exception):
            log.warning("[Crawl4AI] Failed: %s: %s", url, result)
            continue
        rows.append(
            JobListing(
                job_url=url,
                title=url,
                company="",
                location="India",
                description=result,
                source="Crawl4AI",
            )
        )
        log.info("[Crawl4AI] Success: %s", url)
    return rows


class Crawl4AISource(JobSource):
    """Optional generic URL source used by the provider layer."""

    name = "Crawl4AI"

    def __init__(self, urls: Iterable[str] | None = None, *, timeout_seconds: int = 30, max_concurrency: int = 4):
        self.urls = list(urls or [])
        self.timeout_seconds = timeout_seconds
        self.max_concurrency = max_concurrency

    def fetch_listings(self) -> list[JobListing]:
        return crawl_urls(
            self.urls,
            timeout_seconds=self.timeout_seconds,
            max_concurrency=self.max_concurrency,
        )
