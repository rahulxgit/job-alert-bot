import os
import pytest

from sources.crawl4ai import scrape_url


REAL_CRAWL_URL = os.environ.get("CRAWL4AI_REAL_TEST_URL", "")


@pytest.mark.skipif(not REAL_CRAWL_URL, reason="Set CRAWL4AI_REAL_TEST_URL to enable live Crawl4AI validation")
def test_real_job_page_contract():
    listing = scrape_url(
        REAL_CRAWL_URL,
        title="Live Crawl4AI test",
        company="Live test",
        location="India",
        timeout_seconds=30,
    )
    assert listing.job_url == REAL_CRAWL_URL
    assert listing.description
    assert len(listing.description.strip()) >= 300
    assert isinstance(listing.title, str) and listing.title.strip()
