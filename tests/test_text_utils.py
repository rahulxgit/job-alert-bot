"""Tests for pure-logic text helpers — no network, no secrets needed."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.text import extract_email_from_text, guess_company_domain, extract_job_links_from_description


def test_extract_email_from_text_finds_real_email():
    assert extract_email_from_text("Send resume to hr@company.com please") == "hr@company.com"


def test_extract_email_from_text_returns_empty_when_none():
    assert extract_email_from_text("No contact info here") == ""


def test_guess_company_domain_strips_suffixes():
    assert guess_company_domain("Acme Technologies Pvt Ltd") == "acme.com"


def test_guess_company_domain_empty_input():
    assert guess_company_domain("") == ""


def test_extract_job_links_filters_social_noise():
    description = (
        "1. Cognizant - Software Engineer - Apply: https://cognizant.com/careers/job123\n"
        "Follow us: https://instagram.com/placementlelo\n"
        "2. Amazon - SDE Intern - Apply: https://amazon.jobs/en/jobs/456\n"
    )
    links = extract_job_links_from_description(description, "fallback title")
    urls = [url for url, _ in links]
    assert "https://cognizant.com/careers/job123" in urls
    assert "https://amazon.jobs/en/jobs/456" in urls
    assert not any("instagram.com" in u for u in urls)
    assert len(links) == 2


def test_extract_job_links_returns_empty_for_no_links():
    assert extract_job_links_from_description("Just talking, no links here", "title") == []
