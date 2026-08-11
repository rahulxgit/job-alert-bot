"""Tests for the Firecrawl source. Network is mocked throughout — none of
these touch the real Firecrawl API."""
import sys, os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from sources.firecrawl import FirecrawlSource, _normalize_url, _is_job_like


def _mock_response(json_data, status_ok=True):
    resp = MagicMock()
    if status_ok:
        resp.raise_for_status = MagicMock()
    else:
        resp.raise_for_status = MagicMock(side_effect=Exception("HTTP error"))
    resp.json.return_value = json_data
    return resp


@patch("sources.firecrawl.requests.post")
def test_returns_empty_when_no_api_key(mock_post):
    original = config.FIRECRAWL_API_KEY
    config.FIRECRAWL_API_KEY = ""
    try:
        assert FirecrawlSource().fetch_listings() == []
        mock_post.assert_not_called()
    finally:
        config.FIRECRAWL_API_KEY = original


@patch("sources.firecrawl.requests.post")
def test_returns_empty_when_disabled(mock_post):
    original_key, original_enabled = config.FIRECRAWL_API_KEY, config.FIRECRAWL_ENABLED
    config.FIRECRAWL_API_KEY, config.FIRECRAWL_ENABLED = "fc-test", False
    try:
        assert FirecrawlSource().fetch_listings() == []
        mock_post.assert_not_called()
    finally:
        config.FIRECRAWL_API_KEY, config.FIRECRAWL_ENABLED = original_key, original_enabled


@patch("sources.firecrawl.requests.post")
def test_normalizes_into_job_listings(mock_post):
    original_key, original_queries = config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES
    config.FIRECRAWL_API_KEY = "fc-test"
    config.FIRECRAWL_SEARCH_QUERIES = ["React Developer fresher Bangalore"]
    mock_post.return_value = _mock_response({
        "success": True,
        "data": [
            {
                "url": "https://boards.greenhouse.io/acme/jobs/123?utm_source=x",
                "title": "React Developer at Acme",
                "description": "short snippet",
                "markdown": "Full job description text about React and Node fresher role.",
            },
            {
                "url": "https://instagram.com/somepost",
                "title": "not a job",
                "markdown": "",
            },
        ],
    })
    try:
        rows = FirecrawlSource().fetch_listings()
    finally:
        config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES = original_key, original_queries

    assert len(rows) == 1
    job = rows[0]
    assert job.source == "Firecrawl"
    assert job.job_url == "https://boards.greenhouse.io/acme/jobs/123"  # tracking param stripped
    assert "React" in job.description


@patch("sources.firecrawl.requests.post")
def test_query_failure_does_not_crash_pipeline(mock_post):
    original_key, original_queries = config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES
    config.FIRECRAWL_API_KEY = "fc-test"
    config.FIRECRAWL_SEARCH_QUERIES = ["Software Engineer fresher Pune"]
    mock_post.side_effect = Exception("network error")
    try:
        rows = FirecrawlSource().fetch_listings()
    finally:
        config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES = original_key, original_queries
    assert rows == []


@patch("sources.firecrawl.requests.post")
def test_malformed_response_does_not_crash(mock_post):
    original_key, original_queries = config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES
    config.FIRECRAWL_API_KEY = "fc-test"
    config.FIRECRAWL_SEARCH_QUERIES = ["Frontend Developer fresher India"]
    mock_post.return_value = _mock_response({"success": False, "error": "bad request"})
    try:
        rows = FirecrawlSource().fetch_listings()
    finally:
        config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES = original_key, original_queries
    assert rows == []


@patch("sources.firecrawl.requests.post")
def test_duplicate_urls_within_source_are_deduped(mock_post):
    original_key, original_queries = config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES
    config.FIRECRAWL_API_KEY = "fc-test"
    config.FIRECRAWL_SEARCH_QUERIES = ["Full Stack Developer fresher Bangalore", "Full Stack Engineer fresher Bangalore"]
    same_result = {
        "url": "https://naukri.com/job/456?ref=abc",
        "title": "Full Stack Developer - Acme",
        "markdown": "Full stack role description.",
    }
    mock_post.return_value = _mock_response({"success": True, "data": [same_result]})
    try:
        rows = FirecrawlSource().fetch_listings()
    finally:
        config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES = original_key, original_queries
    assert len(rows) == 1


def test_normalize_url_strips_tracking_params():
    assert _normalize_url("https://x.com/job/1?utm_source=fb&id=1") == "https://x.com/job/1?id=1"
    assert _normalize_url("https://x.com/job/1") == "https://x.com/job/1"


def test_is_job_like_rejects_social_domains():
    assert _is_job_like("https://boards.greenhouse.io/acme/jobs/1") is True
    assert _is_job_like("https://instagram.com/p/xyz") is False
    assert _is_job_like("") is False


@patch("sources.firecrawl.requests.post")
def test_api_key_never_appears_in_logs(mock_post, caplog):
    """The real key value must never end up in a log line — it should
    only ever be sent in the Authorization header."""
    import logging
    original_key, original_queries = config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES
    config.FIRECRAWL_API_KEY = "fc-super-secret-value"
    config.FIRECRAWL_SEARCH_QUERIES = ["Software Engineer fresher Pune"]
    mock_post.side_effect = Exception("network error")
    try:
        with caplog.at_level(logging.INFO):
            FirecrawlSource().fetch_listings()
    finally:
        config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES = original_key, original_queries
    assert "fc-super-secret-value" not in caplog.text
