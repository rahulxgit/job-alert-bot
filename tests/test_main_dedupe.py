"""Tests for main.py's dedupe logic."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import JobListing


def test_dedupe_removes_duplicate_urls():
    from main import dedupe
    listings = [
        JobListing(job_url="https://a.com/1", title="A"),
        JobListing(job_url="https://a.com/1", title="A duplicate"),
        JobListing(job_url="https://b.com/2", title="B"),
    ]
    result = dedupe(listings)
    assert len(result) == 2
    assert {l.job_url for l in result} == {"https://a.com/1", "https://b.com/2"}


def test_dedupe_skips_empty_urls():
    from main import dedupe
    listings = [JobListing(job_url="", title="No URL"), JobListing(job_url="https://a.com/1", title="A")]
    assert len(dedupe(listings)) == 1
