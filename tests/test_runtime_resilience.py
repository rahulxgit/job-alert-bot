from unittest.mock import Mock, patch

import config
from models import FitVerdict, JobListing
from ai.gateway_provider import GatewayProvider
from ai.gemini_provider import GeminiProvider
from enrichment import recruiter_email
from sheets.google_sheets import _listing_to_sheet_row, _sheet_value
from utils.llm_json import parse_json_object


def test_sheet_value_converts_lists_to_scalars():
    assert _sheet_value(["San Francisco", "Remote"]) == "San Francisco; Remote"
    assert _sheet_value({"city": "San Francisco"}) == '{"city":"San Francisco"}'


def test_listing_row_contains_only_sheet_scalars():
    listing = JobListing(
        job_url="https://example.com/job/1",
        title="Software Engineer",
        company="Example",
        location=["San Francisco"],
        description="Requirements: React",
    )
    row = _listing_to_sheet_row(listing)
    assert all(isinstance(value, (str, int, float)) for value in row)
    assert row[3] == "San Francisco"


def test_parse_json_object_handles_fenced_and_surrounded_json():
    assert parse_json_object('```json\n{"fit_score": 80, "why": []}\n```')["fit_score"] == 80
    assert parse_json_object('Here is the result: {"fit_score": 70}')['fit_score'] == 70


def test_gateway_normalizes_malformed_shape_values():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "content": '```json\n{"fit_score":"82","is_fresher_appropriate":"true","why":"Strong React fit","gaps":null}\n```'
    }
    with patch("ai.gateway_provider.requests.post", return_value=response):
        verdict = GatewayProvider().evaluate("prompt")
    assert verdict.fit_score == 82
    assert verdict.is_fresher_appropriate is True
    assert verdict.why == ["Strong React fit"]
    assert verdict.gaps == []


def test_gemini_retries_after_malformed_json_then_succeeds():
    malformed = Mock()
    malformed.status_code = 200
    malformed.raise_for_status.return_value = None
    malformed.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"fit_score": 80'}]}}]
    }
    good = Mock()
    good.status_code = 200
    good.raise_for_status.return_value = None
    good.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"fit_score": 80, "is_fresher_appropriate": true, "why": [], "gaps": []}' }]}}]
    }
    with patch("ai.gemini_provider.requests.post", side_effect=[malformed, good]), patch("ai.gemini_provider.time.sleep"):
        verdict = GeminiProvider().evaluate("prompt")
    assert verdict.fit_score == 80


def test_apollo_403_disables_apollo_for_rest_of_run():
    response = Mock()
    response.status_code = 403
    with patch("enrichment.recruiter_email.requests.post", return_value=response):
        recruiter_email._apollo_disabled_for_run = False
        assert recruiter_email._apollo_find_contact("Example", "example.com") == ""
        assert recruiter_email._apollo_disabled_for_run is True


def test_apollo_disabled_state_is_reset_for_each_enrichment_run():
    recruiter_email._apollo_disabled_for_run = True
    listings = [JobListing(job_url="https://example.com/job/1", title="Engineer", company="Example", description="No email")]
    with patch("enrichment.recruiter_email._apollo_find_contact") as mock_apollo:
        recruiter_email.enrich_with_emails(listings)
    mock_apollo.assert_called_once()
