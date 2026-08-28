import pytest
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
from ai.evaluator import _extract_walkin_date, _apply_verdict, keyword_prefilter_score
from models import JobListing, FitVerdict

IST = ZoneInfo("Asia/Kolkata")

def test_adversarial_a():
    # Previous walk-in was held on 20 August 2026. Current walk-in details will be announced soon. -> unknown
    today = datetime.now(IST).date()
    past_date = (today - timedelta(days=10)).strftime("%d %B %Y")
    text = f"Previous walk-in was held on {past_date}. Current walk-in details will be announced soon."
    d1, d2 = _extract_walkin_date(text)
    assert d1 is None and d2 is None

def test_adversarial_b():
    # Previous walk-in: 20 August 2026. Walk-in interview: 30 August 2026. -> 30 August selected
    today = datetime.now(IST).date()
    past_date = (today - timedelta(days=10)).strftime("%d %B %Y")
    future_date = (today + timedelta(days=10)).strftime("%d %B %Y")
    text = f"Previous walk-in: {past_date}. Walk-in interview: {future_date}."
    d1, d2 = _extract_walkin_date(text)
    assert d1 is not None
    assert d1.strftime("%d %B %Y").lower() == future_date.lower()

def test_adversarial_c():
    # Company founded in 2018. Previous drive: 20 August 2026. Walk-in interview: 30 August 2026. -> 30 August selected
    today = datetime.now(IST).date()
    past_date = (today - timedelta(days=10)).strftime("%d %B %Y")
    future_date = (today + timedelta(days=10)).strftime("%d %B %Y")
    text = f"Company founded in 2018. Previous drive: {past_date}. Walk-in interview: {future_date}."
    d1, d2 = _extract_walkin_date(text)
    assert d1 is not None
    assert d1.strftime("%d %B %Y").lower() == future_date.lower()

def test_adversarial_d_and_e():
    # LLM says 2030-01-01, source says 30 August 2026. -> 30 August 2026 wins
    today = datetime.now(IST).date()
    future_date = today + timedelta(days=10)
    future_date_str = future_date.strftime("%d %B %Y")
    desc = f"Walk-in interview: {future_date_str}."
    listing = JobListing(job_url="x", title="SDE Walk-in", description=desc)
    
    # D: LLM hallucinated far future
    verdict_d = FitVerdict(is_walkin=True, walkin_date="2030-01-01", fit_score=85, role_match=25, technical_match=25, experience_match=20, project_match=10, is_fresher_appropriate=True)
    res_d = _apply_verdict(listing, verdict_d)
    assert listing.walkin_date == future_date.strftime("%Y-%m-%d")
    assert getattr(listing, "walkin_date_conflict", False) is True

    # E: LLM hallucinated past date
    listing_e = JobListing(job_url="x", title="SDE Walk-in", description=desc)
    past_llm = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    verdict_e = FitVerdict(is_walkin=True, walkin_date=past_llm, fit_score=85, role_match=25, technical_match=25, experience_match=20, project_match=10, is_fresher_appropriate=True)
    res_e = _apply_verdict(listing_e, verdict_e)
    assert listing_e.walkin_date == future_date.strftime("%Y-%m-%d")
    assert getattr(listing_e, "walkin_date_conflict", False) is True

def test_adversarial_f():
    # F. Source says: "Walk-in interview: 28-30 August 2026." LLM says: 2026-09-10. -> source range remains authoritative.
    today = datetime.now(IST).date()
    start_dt = today - timedelta(days=1)
    end_dt = today + timedelta(days=1)
    desc = f"Walk-in interview: {start_dt.day}-{end_dt.day} {end_dt.strftime('%B %Y')}."
    listing = JobListing(job_url="x", title="SDE Walk-in", description=desc)
    
    # LLM hallucinated
    verdict = FitVerdict(is_walkin=True, walkin_date=(today + timedelta(days=10)).strftime("%Y-%m-%d"), fit_score=85, role_match=25, technical_match=25, experience_match=20, project_match=10, is_fresher_appropriate=True)
    res = _apply_verdict(listing, verdict)
    assert getattr(listing, "walkin_date_conflict", False) is True
    assert listing.verification_status == "active"

def test_adversarial_g():
    # G. Only historical walk-in dates exist. -> unknown, not expired-current.
    today = datetime.now(IST).date()
    past_date = (today - timedelta(days=10)).strftime("%d %B %Y")
    desc = f"Previous walk-in was held on {past_date}."
    d1, d2 = _extract_walkin_date(desc)
    assert d1 is None and d2 is None
