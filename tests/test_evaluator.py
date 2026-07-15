"""Tests for the keyword pre-filter — pure logic, no network needed."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import JobListing
from ai.evaluator import keyword_prefilter_score


def test_senior_role_scores_zero():
    listing = JobListing(job_url="x", title="Senior Software Engineer", description="9-12 years experience required")
    assert keyword_prefilter_score(listing) == 0


def test_fresher_role_scores_positive():
    listing = JobListing(job_url="x", title="SDE 1 Fresher", description="react node.js mongodb fresher entry level")
    assert keyword_prefilter_score(listing) > 0


def test_email_in_description_boosts_score():
    base = JobListing(job_url="x", title="Junior Developer", description="react node fresher")
    with_email = JobListing(job_url="y", title="Junior Developer", description="react node fresher hr@company.com")
    assert keyword_prefilter_score(with_email) > keyword_prefilter_score(base)
