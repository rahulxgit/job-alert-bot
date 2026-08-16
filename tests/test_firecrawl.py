"""Tests for the Firecrawl source. Network is mocked throughout — none of
these touch the real Firecrawl API."""
import sys, os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from sources.firecrawl import FirecrawlSource, _normalize_url, _is_aggregate_page


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
        "data": {
            "web": [
                {
                    "url": "https://boards.greenhouse.io/acme/jobs/123?utm_source=x",
                    "title": "React Developer at Acme",
                    "description": "short snippet",
                    "markdown": "Full job description text about React and Node fresher role.\nRequirements:\n- React\nApply now",

                    "title": "React Developer at Acme",
                    "description": "short snippet",
                    "markdown": "Full job description text about React and Node fresher role.",
                },
                {
                    "url": "https://instagram.com/somepost",
                    "title": "not a job",
                    "markdown": "",
                },
            ]
        },
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
        "markdown": "Full stack role description.\nRequirements:\n- React\nApply now",
    }
    mock_post.return_value = _mock_response({"success": True, "data": {"web": [same_result]}})
    try:
        rows = FirecrawlSource().fetch_listings()
    finally:
        config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES = original_key, original_queries
    assert len(rows) == 1


def test_normalize_url_strips_tracking_params():
    assert _normalize_url("https://x.com/job/1?utm_source=fb&id=1") == "https://x.com/job/1?id=1"
    assert _normalize_url("https://x.com/job/1") == "https://x.com/job/1"


@patch("sources.firecrawl.requests.post")
def test_calls_v2_search_endpoint_with_correct_payload(mock_post):
    """Locks in the verified-current API contract: POST /v2/search,
    Bearer auth, sources=web, scrapeOptions requesting markdown."""
    from sources.firecrawl import SEARCH_URL
    original_key, original_queries = config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES
    config.FIRECRAWL_API_KEY = "fc-test-key"
    config.FIRECRAWL_SEARCH_QUERIES = ["Software Engineer fresher Bangalore"]
    mock_post.return_value = _mock_response({"success": True, "data": {"web": []}})
    try:
        FirecrawlSource().fetch_listings()
    finally:
        config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES = original_key, original_queries

    assert SEARCH_URL == "https://api.firecrawl.dev/v2/search"
    call_args = mock_post.call_args
    assert call_args.args[0] == "https://api.firecrawl.dev/v2/search"
    assert call_args.kwargs["headers"]["Authorization"] == "Bearer fc-test-key"
    body = call_args.kwargs["json"]
    assert body["query"] == "Software Engineer fresher Bangalore"
    assert body["sources"] == [{"type": "web"}]
    assert "markdown" in body["scrapeOptions"]["formats"]


def test_guess_company_regex_does_not_crash_on_edge_case_urls():
    """Regression check for the escaped-dot regex in _guess_company —
    make sure odd URLs (no path, trailing dot, no domain at all) never
    raise instead of just returning a best-effort guess."""
    from sources.firecrawl import _guess_company
    assert _guess_company("Some Title", "https://acme.com/jobs/1") == "Acme"
    assert _guess_company("Some Title", "not-a-url") == ""
    assert _guess_company("Some Title", "") == ""
    assert _guess_company("React Developer at Zeta Corp", "https://x.io/1") == "Zeta Corp"


def test_query_list_covers_all_role_location_combos_with_diverse_phrasing():
    """FIRECRAWL_SEARCH_QUERIES should include every role x location combo
    (not a trimmed subset) and rotate experience-level phrasing across
    them, plus the site-targeted queries — and FIRECRAWL_MAX_QUERIES
    should default to running all of them."""
    expected_combo_count = len(config.FIRECRAWL_ROLE_TERMS) * len(config.FIRECRAWL_LOCATIONS) + len(config.FIRECRAWL_TECH_COMBOS) * len(config.FIRECRAWL_LOCATIONS)
    role_location_queries = [
        q for q in config.FIRECRAWL_SEARCH_QUERIES if "site:" not in q
    ]
    assert len(role_location_queries) == expected_combo_count

    site_queries = [q for q in config.FIRECRAWL_SEARCH_QUERIES if "site:" in q]
    assert len(site_queries) > 0
    assert any("naukri.com" in q for q in site_queries)
    assert any("linkedin.com" in q for q in site_queries)

    # more than one distinct experience-level phrasing actually appears
    phrasings_used = {term for term in config.FIRECRAWL_EXPERIENCE_TERMS if any(term in q for q in role_location_queries)}
    assert len(phrasings_used) > 1

    assert config.FIRECRAWL_MAX_QUERIES == len(config.FIRECRAWL_SEARCH_QUERIES)


def test_guess_posting_date_relative_phrasing():
    from sources.firecrawl import _guess_posting_date
    result = _guess_posting_date("Great role. Posted 2 days ago. Apply now.")
    assert result != ""
    assert "posted 2 day(s) ago" in result


def test_guess_posting_date_posted_today():
    from sources.firecrawl import _guess_posting_date
    from datetime import datetime
    result = _guess_posting_date("This job was posted today by Acme.")
    assert result == datetime.utcnow().strftime("%Y-%m-%d")


def test_guess_posting_date_iso_date():
    from sources.firecrawl import _guess_posting_date
    assert _guess_posting_date("Listing date: 2026-08-01. Apply soon.") == "2026-08-01"


def test_guess_posting_date_returns_empty_when_no_signal():
    from sources.firecrawl import _guess_posting_date
    assert _guess_posting_date("A generic job description with no date info.") == ""
    assert _guess_posting_date("") == ""


@patch("sources.firecrawl.requests.post")
def test_extracted_listings_carry_posting_date_when_present(mock_post):
    original_key, original_queries = config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES
    config.FIRECRAWL_API_KEY = "fc-test"
    config.FIRECRAWL_SEARCH_QUERIES = ["React Developer fresher Bangalore"]
    mock_post.return_value = _mock_response({
        "success": True,
        "data": {
            "web": [{
                "url": "https://boards.greenhouse.io/acme/jobs/999",
                "title": "React Developer at Acme",
                "markdown": "React role, posted 1 day ago. React and Node fresher role.\nRequirements:\n- React\nApply now",
            }]
        },
    })
    try:
        rows = FirecrawlSource().fetch_listings()
    finally:
        config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES = original_key, original_queries

    assert len(rows) == 1
    assert rows[0].posting_date != ""
    assert "1 day(s) ago" in rows[0].posting_date


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


@patch("sources.firecrawl.requests.post")
def test_aggregate_expansion_creates_individual_listings(mock_post):
    from sources.firecrawl import FirecrawlSource
    import config
    original_key, original_queries = config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES
    config.FIRECRAWL_API_KEY = "fc-test"
    config.FIRECRAWL_SEARCH_QUERIES = ["React Developer fresher Bangalore"]

    def side_effect(*args, **kwargs):
        # Determine if it's a search or a scrape call
        url = args[0]
        if "v2/search" in url:
            return _mock_response({
                "success": True,
                "data": {
                    "web": [
                        {
                            "url": "https://example.com/react-developer-jobs",
                            "title": "React Developer Jobs",
                            "markdown": "[React Developer](https://example.com/jobs/react-123)\n\n[Node Developer](https://example.com/jobs/node-456)\n\n[React Developer Duplicate](https://example.com/jobs/react-123)\n\n[About](https://example.com/about)"
                        }
                    ]
                }
            })
        elif "v2/scrape" in url:
            json_body = kwargs.get("json", {})
            req_url = json_body.get("url", "")
            if "react-123" in req_url:
                return _mock_response({
                    "success": True,
                    "data": {
                        "metadata": {"title": "React Developer"},
                        "markdown": "Company: Example Corp\nLocation: Bengaluru\nResponsibilities\nBuild React applications.\nRequirements\nReact\nJavaScript\nTypeScript\n0-1 years experience\nApply now"
                    }
                })
            elif "node-456" in req_url:
                return _mock_response({
                    "success": True,
                    "data": {
                        "metadata": {"title": "Node Developer"},
                        "markdown": "Company: Example Corp\nLocation: Pune\nResponsibilities\nBuild Node.js backend services.\nRequirements\nNode.js\nJavaScript\n0-2 years experience\nApply now"
                    }
                })
        return _mock_response({"success": False})

    mock_post.side_effect = side_effect

    try:
        rows = FirecrawlSource().fetch_listings()
    finally:
        config.FIRECRAWL_API_KEY, config.FIRECRAWL_SEARCH_QUERIES = original_key, original_queries

    # Aggregate URL is never returned
    job_urls = {job.job_url for job in rows}
    assert "https://example.com/react-developer-jobs" not in job_urls

    # Two actual JobListings are returned
    assert len(rows) == 2

    # Job URLs are the actual individual URLs
    assert job_urls == {
        "https://example.com/jobs/react-123",
        "https://example.com/jobs/node-456",
    }

    # Detail-page content is used
    react_job = next(j for j in rows if "react-123" in j.job_url)
    node_job = next(j for j in rows if "node-456" in j.job_url)

    assert "React" in react_job.description
    assert "0-1 years" in react_job.description
    assert "Node.js" in node_job.description
    assert "0-2 years" in node_job.description

    # Duplicate links are processed only once (2 jobs total instead of 3 extracted links)
    assert len([job for job in rows if job.job_url.endswith("/jobs/react-123")]) == 1

    # Ensure /about link was not scraped/returned
    assert "https://example.com/about" not in job_urls


def test_is_aggregate_page_rejects_social_domains():
    from sources.firecrawl import _is_aggregate_page
    assert _is_aggregate_page("https://boards.greenhouse.io/acme/jobs/1") is False
    assert _is_aggregate_page("https://instagram.com/p/xyz") is False
    assert _is_aggregate_page("") is False


def test_is_aggregate_page_identifies_aggregates():
    from sources.firecrawl import _is_aggregate_page

    # These ARE aggregate pages
    assert _is_aggregate_page("https://www.naukri.com/graduate-software-engineer-jobs") == True
    assert _is_aggregate_page("https://www.naukri.com/graduate-software-engineer-jobs-in-bengaluru-bangalore") == True
    assert _is_aggregate_page("https://www.naukri.com/mern-stack-jobs-in-pune-2") == True
    assert _is_aggregate_page("https://in.indeed.com/q-full-stack-developer-fresher-l-bengaluru,-karnataka-jobs.html") == True
    assert _is_aggregate_page("https://www.glassdoor.co.in/Job/bengaluru-entry-level-software-engineer-jobs-...") == True
    assert _is_aggregate_page("https://www.simplyhired.co.in/search?q=react+js+developer&l=pune") == True

    # These ARE NOT aggregate pages
    assert _is_aggregate_page("https://www.linkedin.com/jobs/view/4451665094") == False
    assert _is_aggregate_page("https://internshala.com/job/detail/fresher-reactjs-developer-job-in-bangalore-at-appscrip1774398609") == False
    assert _is_aggregate_page("https://cutshort.io/job/React-JS-Developer-Fresher-...") == False
