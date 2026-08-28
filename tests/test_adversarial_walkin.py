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
    # A. "Company founded in 2018. Previous walk-in: 20 August 2026. Current walk-in date is not announced." -> (None, None)
    today = datetime.now(IST).date()
    past_date = (today - timedelta(days=10)).strftime("%d %B %Y")
    text = f"Company founded in 2018. Previous walk-in: {past_date}. Current walk-in date is not announced."
    d1, d2 = _extract_walkin_date(text)
    assert d1 is None and d2 is None

def test_adversarial_b():
    # B. "Previous walk-in: 20 August 2026. Earlier drive: 25 August 2026. Walk-in interview details will be announced soon." -> (None, None)
    today = datetime.now(IST).date()
    past_date = (today - timedelta(days=10)).strftime("%d %B %Y")
    past_date2 = (today - timedelta(days=5)).strftime("%d %B %Y")
    text = f"Previous walk-in: {past_date}. Earlier drive: {past_date2}. Walk-in interview details will be announced soon."
    d1, d2 = _extract_walkin_date(text)
    assert d1 is None and d2 is None

def test_adversarial_c():
    # C. "Previous walk-in: 20 August 2026. Walk-in interview: 30 August 2026." -> 30 August 2026
    today = datetime.now(IST).date()
    past_date = (today - timedelta(days=10)).strftime("%d %B %Y")
    future_date = (today + timedelta(days=10)).strftime("%d %B %Y")
    text = f"Previous walk-in: {past_date}. Walk-in interview: {future_date}."
    d1, d2 = _extract_walkin_date(text)
    assert d1 is not None
    assert d1.strftime("%d %B %Y").lower() == future_date.lower()

def test_adversarial_d():
    # D. "Company history: 2018. Interview history: 20 August 2026. Current walk-in interview: 30 August 2026." -> 30 August 2026
    today = datetime.now(IST).date()
    past_date = (today - timedelta(days=10)).strftime("%d %B %Y")
    future_date = (today + timedelta(days=10)).strftime("%d %B %Y")
    text = f"Company history: 2018. Interview history: {past_date}. Current walk-in interview: {future_date}."
    d1, d2 = _extract_walkin_date(text)
    assert d1 is not None
    assert d1.strftime("%d %B %Y").lower() == future_date.lower()

def test_adversarial_e():
    # E. "Walk-in interview: 20 August 2026." -> 20 August 2026 then expired/rejected
    today = datetime.now(IST).date()
    past_date = today - timedelta(days=10)
    past_date_str = past_date.strftime("%d %B %Y")
    text = f"Walk-in interview: {past_date_str}."
    d1, d2 = _extract_walkin_date(text)
    assert d1 is not None
    assert d1 == past_date
    
    listing = JobListing(job_url="x", title="SDE Walk-in", description=text)
    verdict = FitVerdict(is_walkin=True, walkin_date=past_date.strftime("%Y-%m-%d"), fit_score=85, role_match=25, technical_match=25, experience_match=20, project_match=10, is_fresher_appropriate=True)
    res = _apply_verdict(listing, verdict)
    assert res is False
    assert listing.verification_status == "expired"
    assert listing.fit_score == 0

def test_adversarial_f():
    # F. "Walk-in interview: 28-30 August 2026." -> start=28 August, end=30 August
    today = datetime.now(IST).date()
    start_dt = today - timedelta(days=1)
    end_dt = today + timedelta(days=1)
    text = f"Walk-in interview: {start_dt.day}-{end_dt.day} {end_dt.strftime('%B %Y')}."
    d1, d2 = _extract_walkin_date(text)
    assert d1 == start_dt
    assert d2 == end_dt

def test_llm_hallucination_future():
    # LLM says 2030-01-01, source says 30 August 2026. -> 30 August 2026 wins
    today = datetime.now(IST).date()
    future_date = today + timedelta(days=10)
    future_date_str = future_date.strftime("%d %B %Y")
    desc = f"Walk-in interview: {future_date_str}."
    listing = JobListing(job_url="x", title="SDE Walk-in", description=desc)
    
    verdict = FitVerdict(is_walkin=True, walkin_date="2030-01-01", fit_score=85, role_match=25, technical_match=25, experience_match=20, project_match=10, is_fresher_appropriate=True)
    res = _apply_verdict(listing, verdict)
    assert listing.walkin_date == future_date.strftime("%Y-%m-%d")
    assert getattr(listing, "walkin_date_conflict", False) is True

def test_llm_hallucination_past():
    # LLM says past date, source says 30 August 2026. -> 30 August 2026 wins
    today = datetime.now(IST).date()
    future_date = today + timedelta(days=10)
    future_date_str = future_date.strftime("%d %B %Y")
    desc = f"Walk-in interview: {future_date_str}."
    listing = JobListing(job_url="x", title="SDE Walk-in", description=desc)
    
    past_llm = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    verdict = FitVerdict(is_walkin=True, walkin_date=past_llm, fit_score=85, role_match=25, technical_match=25, experience_match=20, project_match=10, is_fresher_appropriate=True)
    res = _apply_verdict(listing, verdict)
    assert listing.walkin_date == future_date.strftime("%Y-%m-%d")
    assert getattr(listing, "walkin_date_conflict", False) is True

