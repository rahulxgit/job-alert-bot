"""Generic crawl provider: Crawl4AI first, Firecrawl fallback.

Specialized job sources remain unchanged. This provider is only for generic
web crawling/extraction and returns the same JobListing model as every other
source in the pipeline.
"""
import config
from models import JobListing
from sources.crawl4ai import Crawl4AIError, scrape_url
from sources.firecrawl import FirecrawlSource
from utils.logging_setup import get_logger

log = get_logger("generic-crawler")


def crawl_url(url: str, *, title: str = "", company: str = "", location: str = "India", provider: str | None = None) -> JobListing | None:
    """Use the configured provider; ``auto`` means Crawl4AI then Firecrawl."""
    selected = (provider or config.CRAWL_PROVIDER).lower()
    if selected not in {"auto", "crawl4ai", "firecrawl"}:
        raise ValueError(f"Unsupported CRAWL_PROVIDER: {selected}")

    if selected in {"auto", "crawl4ai"}:
        try:
            return scrape_url(url, title=title, company=company, location=location, timeout_seconds=config.CRAWL4AI_TIMEOUT)
        except Crawl4AIError as exc:
            if selected == "crawl4ai":
                log.warning(f"[Crawl4AI] Failed without fallback: {exc}")
            else:
                log.warning(f"[Firecrawl] Fallback triggered: Crawl4AI failed ({exc})")
                # Fall through only in auto mode.

    if selected in {"auto", "firecrawl"}:
        if not config.FIRECRAWL_ENABLED or not config.FIRECRAWL_API_KEY:
            log.warning("[Firecrawl] Fallback unavailable: provider disabled or API key missing")
            return None

        source = FirecrawlSource()
        try:
            results = source.scrape_url(url, title=title, company=company, location=location)
            return results
        except Exception as exc:
            log.warning(f"[Firecrawl] Fallback failed: {exc}")
            return None

    return None
