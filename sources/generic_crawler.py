"""Generic crawl provider: Crawl4AI first, Firecrawl fallback."""
import config
from models import JobListing
from sources.crawl4ai import Crawl4AIError, scrape_url
from sources.firecrawl import _fetch_job_detail, _guess_company, _guess_location, _guess_posting_date, _is_valid_job_detail
from utils.logging_setup import get_logger

log = get_logger("generic-crawler")


def _firecrawl_scrape_url(url: str, *, title: str = "", company: str = "", location: str = "India") -> JobListing:
    data = _fetch_job_detail(url)
    content = (data or {}).get("markdown", "") if isinstance(data, dict) else ""
    if not _is_valid_job_detail(content):
        raise RuntimeError("Firecrawl returned empty/invalid job content")
    metadata = (data or {}).get("metadata", {}) if isinstance(data, dict) else {}
    final_title = title or metadata.get("title", "") or url
    final_company = company or _guess_company(final_title, url)
    final_location = location or _guess_location(content)
    return JobListing(
        job_url=url,
        title=final_title,
        company=final_company,
        location=final_location,
        description=content,
        source="Firecrawl",
        posting_date=_guess_posting_date(content),
    )


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
                return None
            log.warning(f"[Firecrawl] Fallback triggered: Crawl4AI failed ({exc})")

    if selected in {"auto", "firecrawl"}:
        if not config.FIRECRAWL_ENABLED or not config.FIRECRAWL_API_KEY:
            log.warning("[Firecrawl] Fallback unavailable: provider disabled or API key missing")
            return None
        try:
            listing = _firecrawl_scrape_url(url, title=title, company=company, location=location)
            log.info(f"[Firecrawl] Success: {url}")
            return listing
        except Exception as exc:
            log.warning(f"[Firecrawl] Fallback failed: {exc}")
            return None

    return None
