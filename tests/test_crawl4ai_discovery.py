from unittest.mock import AsyncMock, patch

import config
import main
import sources.crawl4ai_discovery as discovery
from sources.crawl4ai_discovery import _extract_links, _extract_title, _looks_job_url, _looks_like_job_text, _normalize_url


def test_normalize_url_removes_tracking_parameters():
    assert _normalize_url("https://example.com/jobs/1?utm_source=x&ref=abc&page=2") == "https://example.com/jobs/1?page=2"


def test_job_url_classifier_accepts_supported_detail_pages_and_rejects_aggregates():
    assert _looks_job_url("https://boards.greenhouse.io/acme/jobs/123", "Software Engineer")
    assert _looks_job_url("https://jobs.lever.co/acme/software-engineer-123", "Software Engineer")
    assert _looks_job_url("https://naukri.com/job-listings-software-engineer-123", "Software Engineer")
    assert _looks_job_url("https://internshala.com/job/detail/software-engineer-123", "Software Engineer")
    assert _looks_job_url("https://wellfound.com/jobs/software-engineer-123", "Software Engineer")
    assert _looks_job_url("https://www.linkedin.com/jobs/view/123456", "Software Engineer")
    assert _looks_job_url("https://www.indeed.com/viewjob?jk=abc123", "Software Engineer")
    assert _looks_job_url("https://www.ycombinator.com/companies/acme/jobs/software-engineer", "Software Engineer")
    assert _looks_job_url("https://cutshort.io/job/software-engineer-123", "Software Engineer")
    assert _looks_job_url("https://www.instahyre.com/job/software-engineer-123", "Software Engineer")
    assert _looks_job_url("https://www.hiringcafe.com/jobs/software-engineer-123", "Software Engineer")
    assert _looks_job_url("https://example.com/job/software-engineer-123", "Software Engineer") is False
    assert not _looks_job_url("https://boards.greenhouse.io/search?q=software-engineer", "Search results")


def test_job_text_requires_reasonable_detail_content():
    assert not _looks_like_job_text("Software Engineer")
    assert _looks_like_job_text("Software Engineer\nRequirements\nReact, Node.js\n" + "x" * 450)


def test_extract_links_normalizes_and_deduplicates():
    markdown = "[Job](https://example.com/jobs/1?utm_source=x)\n[Same](https://example.com/jobs/1)"
    assert _extract_links(markdown, "https://example.com") == ["https://example.com/jobs/1"]


def test_discovery_source_is_registered_in_pipeline():
    names = [source.name for source in main.ALL_SOURCES]
    assert "Crawl4AI Discovery" in names


def test_discovery_can_be_disabled_without_network_calls():
    original = config.CRAWL4AI_DISCOVERY_ENABLED
    config.CRAWL4AI_DISCOVERY_ENABLED = False
    try:
        with patch("sources.crawl4ai_discovery.discover_job_listings") as mock_discover:
            from sources.crawl4ai_discovery import Crawl4AIDiscoverySource
            assert Crawl4AIDiscoverySource().fetch_listings() == []
            mock_discover.assert_not_called()
    finally:
        config.CRAWL4AI_DISCOVERY_ENABLED = original


def test_discovery_seed_concurrency_is_configurable(monkeypatch):
    monkeypatch.setattr(config, "CRAWL4AI_DISCOVERY_SEED_CONCURRENCY", 3)
    assert config.CRAWL4AI_DISCOVERY_SEED_CONCURRENCY == 3


def test_discovery_seeds_run_with_bounded_concurrency(monkeypatch):
    seeds = [
        "https://boards.greenhouse.io/",
        "https://jobs.lever.co/",
        "https://jobs.ashbyhq.com/",
    ]
    monkeypatch.setattr(config, "CRAWL4AI_DISCOVERY_SEED_URLS", seeds)
    monkeypatch.setattr(config, "CRAWL4AI_DISCOVERY_MAX_SEEDS", 3)
    monkeypatch.setattr(config, "CRAWL4AI_DISCOVERY_SEED_CONCURRENCY", 3)

    class FakeCrawler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_seed(crawler, seed, run_config):
        # (seed, discovered, pages_seen, request_success, candidate_urls_found, anti_bot_detected)
        return seed, [], 1, True, 1, False

    with patch.object(discovery, "AsyncWebCrawler", return_value=FakeCrawler()):
        with patch.object(discovery, "_crawl_seed", new=AsyncMock(side_effect=fake_seed)) as mock_seed:
            rows, metrics = __import__("asyncio").run(discovery._discover())

    assert rows == []
    assert metrics.seeds_attempted == 3
    assert metrics.seeds_succeeded == 3
    assert metrics.seed_failures == 0
    assert metrics.pages_seen == 3
    assert metrics.candidate_urls_found == 3
    assert mock_seed.await_count == 3


def test_discovery_raises_when_seeds_succeed_but_find_zero_candidates(monkeypatch):
    """Reproduces the reported incident: 12 seeds technically succeed but
    extraction finds zero job-shaped URLs. Transport success must not be
    reported as discovery success."""
    seeds = ["https://boards.greenhouse.io/", "https://jobs.lever.co/"]
    monkeypatch.setattr(config, "CRAWL4AI_DISCOVERY_SEED_URLS", seeds)
    monkeypatch.setattr(config, "CRAWL4AI_DISCOVERY_MAX_SEEDS", 2)
    monkeypatch.setattr(config, "CRAWL4AI_DISCOVERY_SEED_CONCURRENCY", 2)

    class FakeCrawler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_seed(crawler, seed, run_config):
        return seed, [], 5, True, 0, False

    with patch.object(discovery, "AsyncWebCrawler", return_value=FakeCrawler()):
        with patch.object(discovery, "_crawl_seed", new=AsyncMock(side_effect=fake_seed)):
            try:
                __import__("asyncio").run(discovery._discover())
            except RuntimeError as exc:
                assert "zero job-shaped candidate URLs" in str(exc)
            else:
                raise AssertionError("technically-successful zero-candidate run was not flagged")


def test_discovery_raises_blocked_when_anti_bot_pages_detected(monkeypatch):
    seeds = ["https://boards.greenhouse.io/", "https://jobs.lever.co/"]
    monkeypatch.setattr(config, "CRAWL4AI_DISCOVERY_SEED_URLS", seeds)
    monkeypatch.setattr(config, "CRAWL4AI_DISCOVERY_MAX_SEEDS", 2)
    monkeypatch.setattr(config, "CRAWL4AI_DISCOVERY_SEED_CONCURRENCY", 2)

    class FakeCrawler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_seed(crawler, seed, run_config):
        return seed, [], 1, True, 0, True

    with patch.object(discovery, "AsyncWebCrawler", return_value=FakeCrawler()):
        with patch.object(discovery, "_crawl_seed", new=AsyncMock(side_effect=fake_seed)):
            try:
                __import__("asyncio").run(discovery._discover())
            except RuntimeError as exc:
                assert "anti-bot" in str(exc) or "BLOCKED" in str(exc)
            else:
                raise AssertionError("anti-bot pages were not flagged as blocked")


def test_looks_like_anti_bot_detects_short_challenge_pages():
    assert discovery._looks_like_anti_bot("Just a moment...\nChecking your browser before accessing.")
    assert not discovery._looks_like_anti_bot("Software Engineer\nRequirements\n" + "x" * 400)


def test_extract_title_prefers_real_page_title_over_first_markdown_line():
    # A real job page's <title> tag should win over nav junk that happens to
    # render first in the markdown.
    markdown = "Close\n\nSoftware Engineer - Backend\nRequirements..."
    assert _extract_title(markdown, "Backend Engineer at Acme Corp") == "Backend Engineer at Acme Corp"


def test_extract_title_rejects_nav_chrome_lines():
    # Reproduces the reported incident: garbage "titles" like bare nav links
    # and modal buttons were being fed into the AI evaluator as fake candidates.
    assert _extract_title("Close\nSoftware Engineer\nRequirements", "") == "Software Engineer"
    assert _extract_title("[About](https://www.ycombinator.com/about)\nFull Stack Developer", "") == "Full Stack Developer"
    assert _extract_title("[](https://wellfound.com/)\nProduct Engineer", "") == "Product Engineer"


def test_extract_title_unwraps_nested_image_link_markdown():
    # Nested image-in-link markdown (a logo wrapped in a link) must never be
    # returned as raw markdown syntax — it should unwrap to plain text even
    # when that text is a logo caption rather than a real job title.
    markdown = "[![Cutshort logo](https://cutshort.io/logo.png)](https://cutshort.io/)\nBackend Engineer"
    title = _extract_title(markdown, "")
    assert "[" not in title and "(" not in title
    assert title == "Cutshort logo"


def test_extract_title_falls_back_to_default_when_nothing_usable():
    assert _extract_title("Close\n[](https://x.com/)", "") == "Software Engineer"
