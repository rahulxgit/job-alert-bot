from models import JobListing
from utils.job_quality import canonical_url, data_quality_score, deduplicate_jobs, normalize_location, normalize_title, rank_candidates


def job(url, title="Software Engineer", company="Example", location="Bangalore", description="React Node JavaScript requirements experience skills", posting_date="2026-08-14"):
    return JobListing(job_url=url, title=title, company=company, location=location, description=description, posting_date=posting_date)


def test_normalization_and_tracking_url_cleanup():
    assert normalize_location("Bangalore, India") == "bengaluru, india"
    assert normalize_title("Software Engineer (Remote)") == "software engineer"
    assert canonical_url("HTTPS://Example.com/job/123/?utm_source=x&ref=y") == "https://example.com/job/123"


def test_cross_source_duplicate_keeps_best_description():
    weak = job("https://source-a.example/job/1", description="React role")
    strong = job("https://source-b.example/job/2", description="React Node JavaScript requirements responsibilities qualifications experience skills MongoDB SQL")
    deduped, removed = deduplicate_jobs([weak, strong])
    assert removed == 1
    assert len(deduped) == 1
    assert deduped[0].job_url == strong.job_url
    assert data_quality_score(deduped[0]) > data_quality_score(weak)


def test_same_company_title_location_but_different_descriptions_are_preserved():
    first = job("https://example.com/a", description="React frontend role with 0-1 years experience")
    second = job("https://example.com/b", description="Java backend role requiring 3-5 years experience and Spring")
    deduped, removed = deduplicate_jobs([first, second])
    assert len(deduped) == 2
    assert removed == 0


def test_ranking_prefers_profile_relevant_recent_job_without_company_bonus():
    irrelevant = job("https://example.com/old", title="Senior Architect", location="Delhi", description="Java architecture and 8 years experience", posting_date="2026-07-01")
    relevant = job("https://example.com/new", title="React Node Full Stack Engineer", location="Bengaluru", description="React Node JavaScript MERN fresher entry-level requirements skills", posting_date="2026-08-14")
    ranked = rank_candidates([irrelevant, relevant])
    assert ranked[0].job_url == relevant.job_url
    assert relevant.prefilter_score > irrelevant.prefilter_score
