import pytest
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
import config
from models import JobListing, FitVerdict
from ai.evaluator import keyword_prefilter_score, _apply_verdict, _education_score

def test_acceptance_mechanical_engineer():
    listing = JobListing(job_url="url", title="Mechanical Engineer", description="Must know Python and CAD. Fresher.")
    score = keyword_prefilter_score(listing)
    assert score == 0

def test_acceptance_business_developer():
    listing = JobListing(job_url="url", title="Business Developer", description="React to client needs. Sales role. Fresher.")
    score = keyword_prefilter_score(listing)
    assert score == 0

def test_acceptance_generic_btech_vs_any_branch():
    res1, reject1 = _education_score("Must have B.Tech degree")
    assert reject1 is False
    assert res1 == 2
    
    res2, reject2 = _education_score("Must have B.Tech in any engineering branch")
    assert reject2 is False
    assert res2 == 4

    res3, reject3 = _education_score("B.Tech in Computer Science candidates only")
    assert reject3 is True
    assert res3 == 0

def test_acceptance_walkin_rejection_and_boost():
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    listing_upcoming = JobListing(job_url="url", title="SDE", description=f"Walk-in drive. {tomorrow.strftime('%Y-%m-%d')}")
    score_upcoming = keyword_prefilter_score(listing_upcoming)
    assert score_upcoming > 0
    
    listing_yesterday = JobListing(job_url="url", title="SDE", description=f"Walk-in drive. {yesterday.strftime('%Y-%m-%d')}")
    score_yesterday = keyword_prefilter_score(listing_yesterday)
    assert score_yesterday == 0

    listing_llm = JobListing(job_url="url", title="SDE", description="Walk-in drive")
    verdict_expired = FitVerdict(is_walkin=True, walkin_date=yesterday.strftime('%Y-%m-%d'), fit_score=85, role_match=30, technical_match=20, experience_match=20, location_match=5, is_fresher_appropriate=True)
    res = _apply_verdict(listing_llm, verdict_expired)
    assert res is False
    assert listing_llm.fit_score == 0
    assert listing_llm.verification_status == "expired"

    verdict_upcoming = FitVerdict(is_walkin=True, walkin_date=tomorrow.strftime('%Y-%m-%d'), fit_score=85, role_match=30, technical_match=20, experience_match=20, location_match=5, is_fresher_appropriate=True)
    res2 = _apply_verdict(listing_llm, verdict_upcoming)
    assert res2 is True
    assert listing_llm.verification_status == "upcoming"

def test_acceptance_customer_support_walkin():
    listing = JobListing(job_url="url", title="Customer Support Walk-in", description="BPO hiring drive")
    score = keyword_prefilter_score(listing)
    assert score == 0

def test_acceptance_immediate_joiner_not_walkin():
    from ai.evaluator import _contains_any
    assert not _contains_any("immediate joiner", config.WALKIN_POSITIVE_SIGNALS)
