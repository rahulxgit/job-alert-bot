"""Provider and bound tests; all network/browser behavior is mocked."""
from unittest.mock import patch

import config
from models import JobListing
from sources.crawl4ai import Crawl4AIError
from sources.generic_crawler import crawl_url


def _job(source):
    return JobListing(job_url="https://example.com/job/1", title="Software Engineer", description="Requirements\nReact", source=source)


@patch("sources.generic_crawler._firecrawl_scrape_url")
@patch("sources.generic_crawler.scrape_url")
def test_auto_uses_crawl4ai_without_firecrawl(mock_crawl, mock_firecrawl):
    mock_crawl.return_value = _job("Crawl4AI")
    original = config.CRAWL_PROVIDER
    config.CRAWL_PROVIDER = "auto"
    try:
        result = crawl_url("https://example.com/job/1")
    finally:
        config.CRAWL_PROVIDER = original
    assert result.source == "Crawl4AI"
    mock_firecrawl.assert_not_called()


@patch("sources.generic_crawler._firecrawl_scrape_url")
@patch("sources.generic_crawler.scrape_url", side_effect=Crawl4AIError("timeout"))
def test_auto_falls_back_to_firecrawl(mock_crawl, mock_firecrawl):
    mock_firecrawl.return_value = _job("Firecrawl")
    original_key, original_provider = config.FIRECRAWL_API_KEY, config.CRAWL_PROVIDER
    config.FIRECRAWL_API_KEY, config.CRAWL_PROVIDER = "test-key", "auto"
    try:
        result = crawl_url("https://example.com/job/1")
    finally:
        config.FIRECRAWL_API_KEY, config.CRAWL_PROVIDER = original_key, original_provider
    assert result.source == "Firecrawl"
    mock_crawl.assert_called_once()
    mock_firecrawl.assert_called_once()


@patch("sources.generic_crawler._firecrawl_scrape_url")
@patch("sources.generic_crawler.scrape_url", side_effect=Crawl4AIError("blocked"))
def test_crawl4ai_mode_does_not_call_firecrawl(mock_crawl, mock_firecrawl):
    original = config.CRAWL_PROVIDER
    config.CRAWL_PROVIDER = "crawl4ai"
    try:
        assert crawl_url("https://example.com/job/1") is None
    finally:
        config.CRAWL_PROVIDER = original
    mock_firecrawl.assert_not_called()


def test_invalid_provider_is_rejected():
    original = config.CRAWL_PROVIDER
    config.CRAWL_PROVIDER = "invalid"
    try:
        try:
            crawl_url("https://example.com")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid provider was accepted")
    finally:
        config.CRAWL_PROVIDER = original
