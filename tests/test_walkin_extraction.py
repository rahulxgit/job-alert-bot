import pytest
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
from ai.evaluator import _extract_walkin_date, _apply_verdict, keyword_prefilter_score
from models import JobListing, FitVerdict

IST = ZoneInfo("Asia/Kolkata")

def test_walkin_date_extraction_cases():
    today = datetime.now(IST).date()
    
    # A
    future_date = (today + timedelta(days=10)).strftime("%d %B %Y")
    text_a = f"Company established on 10 March 2018. Walk-in interview on {future_date}."
    d1, d2 = _extract_walkin_date(text_a)
    assert d1.strftime("%d %B %Y").lower() == future_date.lower()

    # B
    text_b = "Company founded 10 March 2018. Walk-in interview details will be announced soon."
    d1, d2 = _extract_walkin_date(text_b)
    assert d1 is None and d2 is None

    # C
    past_date = (today - timedelta(days=10)).strftime("%d %B %Y")
    text_c = f"Previous walk-in was held on {past_date}."
    d1, d2 = _extract_walkin_date(text_c)
    assert d1 is None and d2 is None

    # D
    text_d = f"Walk-in interview: {past_date}."
    d1, d2 = _extract_walkin_date(text_d)
    assert d1 is not None and d2 is not None

    # E
    text_e = f"Walk-in interview: {future_date}."
    d1, d2 = _extract_walkin_date(text_e)
    assert d1 is not None and d2 is not None

    # F
    start_dt = today - timedelta(days=1)
    end_dt = today + timedelta(days=1)
    text_f = f"Walk-in interview: {start_dt.day}-{end_dt.day} {end_dt.strftime('%B %Y')}."
    d1, d2 = _extract_walkin_date(text_f)
    assert d1 == start_dt and d2 == end_dt

    # G
    past_start = today - timedelta(days=5)
    past_end = today - timedelta(days=3)
    text_g = f"Walk-in interview: {past_start.day}-{past_end.day} {past_end.strftime('%B %Y')}."
    d1, d2 = _extract_walkin_date(text_g)
    assert d1 == past_start and d2 == past_end

    # H
    text_h = f"Experience: 2 years. Established: 2018. Founded: 2017. Walk-in interview: {future_date}."
    d1, d2 = _extract_walkin_date(text_h)
    assert d1.strftime("%d %B %Y").lower() == future_date.lower()

def test_apply_verdict_range_handling():
    today = datetime.now(IST).date()
    
    # Active range
    start_dt = today - timedelta(days=1)
    end_dt = today + timedelta(days=1)
    desc_f = f"Walk-in interview: {start_dt.day}-{end_dt.day} {end_dt.strftime('%B %Y')}."
    
    listing = JobListing(job_url="x", title="Software Engineer Walk-in", description=desc_f)
    # The LLM sees the text and guesses today
    verdict = FitVerdict(is_walkin=True, walkin_date=today.strftime("%Y-%m-%d"), fit_score=85, role_match=25, technical_match=25, experience_match=20, project_match=10, is_fresher_appropriate=True)
    res = _apply_verdict(listing, verdict)
    assert res is True
    assert listing.verification_status == "active"

    # Expired range
    past_start = today - timedelta(days=5)
    past_end = today - timedelta(days=3)
    desc_g = f"Walk-in interview: {past_start.day}-{past_end.day} {past_end.strftime('%B %Y')}."
    
    listing_expired = JobListing(job_url="x", title="Software Engineer Walk-in", description=desc_g)
    # The LLM guesses an expired date
    verdict_exp = FitVerdict(is_walkin=True, walkin_date=past_end.strftime("%Y-%m-%d"), fit_score=85, role_match=25, technical_match=25, experience_match=20, project_match=10, is_fresher_appropriate=True)
    res_exp = _apply_verdict(listing_expired, verdict_exp)
    assert res_exp is False
    assert listing_expired.verification_status == "expired"
    assert listing_expired.fit_score == 0

def test_apply_verdict_historical_rejection():
    today = datetime.now(IST).date()
    # E.g. JD with historical date
    desc = "Previous walk-in was held on 10 August 2026. Walk-in interview details will be announced soon."
    listing = JobListing(job_url="x", title="Software Engineer Walk-in", description=desc)
    
    # LLM wrongly hallucinates 10 August 2026
    verdict = FitVerdict(is_walkin=True, walkin_date="2026-08-10", fit_score=85, role_match=25, technical_match=25, experience_match=20, project_match=10, is_fresher_appropriate=True)
    res = _apply_verdict(listing, verdict)
    
    # The extraction finds None (because it's historical). It falls through to valid_date = wd (the LLM date) IF start_date/end_date are None.
    # Wait, if start_date/end_date is None, the LLM date is tentatively trusted.
    # But 10 August 2026 is expired, so it is rejected anyway.
    assert res is False
