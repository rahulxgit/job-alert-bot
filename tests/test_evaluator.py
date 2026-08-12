"""Tests for the keyword pre-filter and parsing logic."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import JobListing
from ai.evaluator import keyword_prefilter_score, _parse_experience, prefilter
import config

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

def test_parse_experience_eligible_formats():
    cases = [
        "Freshers welcome",
        "Fresh graduate",
        "New grad",
        "0 years",
        "0-1 years",
        "0-1 yrs",
        "0–1 years",
        "0-2 years",
        "0–2 years",
        "1 year experience",
        "1+ years",
        "up to 1 year"
    ]
    for c in cases:
        res = _parse_experience(c)
        assert res["eligible_for_rahul"] == True, f"Failed on: {c}"

def test_parse_experience_rejects_mandatory():
    cases = [
        "2+ years required",
        "minimum 2 years",
        "2 years required",
        "2-3 years required",
        "2-4 years required",
        "3+ years required",
        "5+ years required",
    ]
    for c in cases:
        res = _parse_experience(c)
        assert res["eligible_for_rahul"] == False, f"Failed on: {c}"

def test_parse_experience_allows_preferred_when_fresher_friendly():
    cases = [
        "2+ years preferred, freshers welcome",
        "3 years preferred, new grad",
        "experience is a plus, entry level"
    ]
    for c in cases:
        res = _parse_experience(c)
        assert res["eligible_for_rahul"] == True, f"Failed on: {c}"

def test_prefilter_allocation_fairness():
    # Simulate an imbalanced pool
    sources = []
    # 2500 greenhouse
    sources.extend([JobListing(job_url=f"greenhouse/{i}", title="dev", description="fresher", source="Greenhouse") for i in range(2500)])
    # 1300 linkedin
    sources.extend([JobListing(job_url=f"linkedin/{i}", title="dev", description="fresher", source="LinkedIn") for i in range(1300)])
    # 200 internshala
    sources.extend([JobListing(job_url=f"internshala/{i}", title="dev", description="fresher", source="Internshala") for i in range(200)])
    # 150 firecrawl
    sources.extend([JobListing(job_url=f"firecrawl/{i}", title="dev", description="fresher", source="Firecrawl") for i in range(150)])
    # 100 wellfound
    sources.extend([JobListing(job_url=f"wellfound/{i}", title="dev", description="fresher", source="Wellfound") for i in range(100)])

    # Store old limits
    old_max = config.MAX_LLM_CANDIDATES
    config.MAX_LLM_CANDIDATES = 300
    config.MIN_CANDIDATES_PER_SOURCE = 5

    pool = prefilter(sources)

    config.MAX_LLM_CANDIDATES = old_max

    # Verify pool size is constrained
    assert len(pool) <= 300

    # Verify fair distribution: every source should have representation
    source_counts = {}
    for p in pool:
        source_counts[p.source] = source_counts.get(p.source, 0) + 1

    for src in ["Greenhouse", "LinkedIn", "Internshala", "Firecrawl", "Wellfound"]:
        assert source_counts.get(src, 0) >= 5
