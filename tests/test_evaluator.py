"""Tests for the precise keyword pre-filter and parsing logic."""
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import JobListing
from ai.evaluator import keyword_prefilter_score, _parse_experience, prefilter
import config


def test_senior_role_scores_zero():
    listing = JobListing(
        job_url="x",
        title="Senior Software Engineer",
        description="9-12 years experience required react node.js",
    )
    assert keyword_prefilter_score(listing) == 0


def test_fresher_role_scores_positive():
    listing = JobListing(
        job_url="x",
        title="SDE 1 Fresher",
        description="react node.js mongodb fresher entry level",
        location="Bengaluru, India",
    )
    assert keyword_prefilter_score(listing) > 0


def test_mechanical_design_engineer_with_python_is_rejected():
    listing = JobListing(
        job_url="x",
        title="Mechanical Design Engineer",
        description="Python database SQL",
        location="Pune, India",
    )
    assert keyword_prefilter_score(listing) == 0


def test_software_engineer_with_python_is_eligible():
    listing = JobListing(
        job_url="x",
        title="Software Engineer",
        description="Python fresher friendly",
        location="Pune, India",
    )
    assert keyword_prefilter_score(listing) >= config.MIN_LIGHTWEIGHT_SCORE


def test_electrical_engineer_with_sql_is_rejected():
    listing = JobListing(
        job_url="x",
        title="Electrical Engineer",
        description="SQL database backend experience required",
        location="Pune, India",
    )
    assert keyword_prefilter_score(listing) == 0


def test_backend_engineer_with_sql_is_eligible():
    listing = JobListing(
        job_url="x",
        title="Backend Engineer",
        description="SQL database fresher friendly",
        location="Pune, India",
    )
    assert keyword_prefilter_score(listing) >= config.MIN_LIGHTWEIGHT_SCORE


def test_outside_preferred_geography_is_rejected():
    listing = JobListing(
        job_url="x",
        title="Software Engineer",
        description="React Node.js fresher",
        location="New York, United States",
    )
    assert keyword_prefilter_score(listing) == 0


def test_hard_cs_only_degree_requirement_is_rejected():
    listing = JobListing(
        job_url="x",
        title="Software Engineer",
        description="React Node.js. B.Tech in Computer Science only. Freshers welcome.",
        location="Bengaluru, India",
    )
    assert keyword_prefilter_score(listing) == 0


def test_any_engineering_branch_remains_eligible():
    listing = JobListing(
        job_url="x",
        title="Graduate Software Engineer",
        description="React Node.js. Any engineering branch. 0-2 years.",
        location="Hyderabad, India",
    )
    assert keyword_prefilter_score(listing) >= config.MIN_LIGHTWEIGHT_SCORE


def test_old_dated_listing_is_rejected():
    old_date = (datetime.now(timezone.utc) - timedelta(days=config.FRESHNESS_DAYS + 1)).strftime("%Y-%m-%d")
    listing = JobListing(
        job_url="x",
        title="Software Engineer",
        description="React Node.js fresher",
        location="Bengaluru, India",
        posting_date=old_date,
    )
    assert keyword_prefilter_score(listing) == 0


def test_email_in_description_still_boosts_score():
    base = JobListing(
        job_url="x",
        title="Junior Software Developer",
        description="React Node.js fresher",
        location="Bengaluru, India",
    )
    with_email = JobListing(
        job_url="y",
        title="Junior Software Developer",
        description="React Node.js fresher hr@company.com",
        location="Bengaluru, India",
    )
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
        "up to 1 year",
    ]
    for c in cases:
        res = _parse_experience(c)
        assert res["eligible_for_rahul"] is True, f"Failed on: {c}"


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
        assert res["eligible_for_rahul"] is False, f"Failed on: {c}"


def test_parse_experience_allows_preferred_when_fresher_friendly():
    cases = [
        "2+ years preferred, freshers welcome",
        "3 years preferred, new grad",
        "experience is a plus, entry level",
    ]
    for c in cases:
        res = _parse_experience(c)
        assert res["eligible_for_rahul"] is True, f"Failed on: {c}"


def test_prefilter_preserves_300_candidate_cap_and_source_fairness():
    sources = []
    template = "Software Engineer fresher React Node.js MongoDB entry level"
    for i in range(2500):
        sources.append(JobListing(
            job_url=f"greenhouse/{i}", title="Software Engineer", description=template,
            location="Bengaluru, India", source="Greenhouse",
        ))
    for i in range(1300):
        sources.append(JobListing(
            job_url=f"linkedin/{i}", title="SDE 1", description=template,
            location="Pune, India", source="LinkedIn",
        ))
    for i in range(200):
        sources.append(JobListing(
            job_url=f"internshala/{i}", title="Full Stack Developer", description=template,
            location="Hyderabad, India", source="Internshala",
        ))
    for i in range(150):
        sources.append(JobListing(
            job_url=f"firecrawl/{i}", title="React Developer", description=template,
            location="Remote", source="Firecrawl",
        ))
    for i in range(100):
        sources.append(JobListing(
            job_url=f"wellfound/{i}", title="Backend Developer", description=template,
            location="India", source="Wellfound",
        ))

    old_max = config.MAX_LLM_CANDIDATES
    old_min_slots = config.MIN_CANDIDATES_PER_SOURCE
    config.MAX_LLM_CANDIDATES = 300
    config.MIN_CANDIDATES_PER_SOURCE = 5

    try:
        pool = prefilter(sources)
    finally:
        config.MAX_LLM_CANDIDATES = old_max
        config.MIN_CANDIDATES_PER_SOURCE = old_min_slots

    assert len(pool) <= 300
    source_counts = {}
    for p in pool:
        source_counts[p.source] = source_counts.get(p.source, 0) + 1
    for src in ["Greenhouse", "LinkedIn", "Internshala", "Firecrawl", "Wellfound"]:
        assert source_counts.get(src, 0) >= 5
