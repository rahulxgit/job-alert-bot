from sources.crawl4ai_discovery import _extract_links, _looks_job_url, _looks_like_job_text, _normalize_url


def test_normalize_url_removes_tracking_parameters():
    assert _normalize_url("https://example.com/jobs/1?utm_source=x&ref=abc&page=2") == "https://example.com/jobs/1?page=2"


def test_job_url_classifier_accepts_detail_pages_and_rejects_aggregates():
    assert _looks_job_url("https://boards.greenhouse.io/acme/jobs/123", "Software Engineer")
    assert _looks_job_url("https://example.com/job/software-engineer-123", "Software Engineer")
    assert not _looks_job_url("https://example.com/search?q=software-engineer", "Search results")


def test_job_text_requires_reasonable_detail_content():
    assert not _looks_like_job_text("Software Engineer")
    assert _looks_like_job_text("Software Engineer\nRequirements\nReact, Node.js\n" + "x" * 450)


def test_extract_links_normalizes_and_deduplicates():
    markdown = "[Job](https://example.com/jobs/1?utm_source=x)\n[Same](https://example.com/jobs/1)"
    assert _extract_links(markdown, "https://example.com") == ["https://example.com/jobs/1"]
