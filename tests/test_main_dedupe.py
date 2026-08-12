"""Tests for deduplication logic."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import JobListing
from main import dedupe, _normalize_url

def test_dedupe_removes_duplicate_urls():
    jobs = [
        JobListing(job_url="http://x.com/1", title="A"),
        JobListing(job_url="http://x.com/1", title="B"),
        JobListing(job_url="http://x.com/2", title="C"),
    ]
    unique = dedupe(jobs)
    assert len(unique) == 2
    urls = {j.job_url for j in unique}
    assert "http://x.com/1" in urls
    assert "http://x.com/2" in urls

def test_dedupe_skips_empty_urls():
    jobs = [
        JobListing(job_url="", title="A"),
        JobListing(job_url="", title="B"),
    ]
    unique = dedupe(jobs)
    # Dedupe returns empty if URL is empty, wait, the implementation allows empty?
    # Actually if norm_url is empty, it evaluates to false so it skips
    assert len(unique) == 0

def test_url_normalization_strips_params():
    assert _normalize_url("https://example.com/job?utm_source=linkedin") == "https://example.com/job"
    assert _normalize_url("https://example.com/job?ref=123&other=456") == "https://example.com/job?other=456"
    assert _normalize_url("https://example.com/job") == "https://example.com/job"
