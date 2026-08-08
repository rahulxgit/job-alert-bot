"""Tests for Arbeitnow and RemoteOK sources — network is mocked, so these
check the keyword filtering and parsing logic, not live connectivity."""
import sys, os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources.arbeitnow import ArbeitnowSource
from sources.remoteok import RemoteOKSource


def _mock_response(json_data):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data
    return resp


@patch("sources.arbeitnow.requests.get")
def test_arbeitnow_filters_by_keyword(mock_get):
    mock_get.return_value = _mock_response({
        "data": [
            {"title": "React Developer", "company_name": "Acme", "url": "https://a.co/1",
             "tags": ["react"], "remote": True, "description": "React role"},
            {"title": "Sales Manager", "company_name": "Beta", "url": "https://b.co/2",
             "tags": ["sales"], "remote": False, "description": "Sales role"},
        ]
    })
    rows = ArbeitnowSource().fetch_listings()
    assert len(rows) == 1
    assert rows[0].title == "React Developer"


@patch("sources.arbeitnow.requests.get")
def test_arbeitnow_returns_empty_on_failure(mock_get):
    mock_get.side_effect = Exception("network error")
    assert ArbeitnowSource().fetch_listings() == []


@patch("sources.remoteok.requests.get")
def test_remoteok_skips_legal_notice_and_filters(mock_get):
    mock_get.return_value = _mock_response([
        {"legal": "notice text, no position field"},
        {"position": "Junior Frontend Engineer", "company": "Acme",
         "url": "/remote-jobs/1", "tags": ["react", "junior"], "location": "Remote"},
        {"position": "Senior Sales Director", "company": "Beta",
         "url": "/remote-jobs/2", "tags": ["sales"], "location": "Remote"},
    ])
    rows = RemoteOKSource().fetch_listings()
    assert len(rows) == 1
    assert rows[0].title == "Junior Frontend Engineer"
    assert rows[0].job_url == "https://remoteok.com/remote-jobs/1"


@patch("sources.remoteok.requests.get")
def test_remoteok_returns_empty_on_failure(mock_get):
    mock_get.side_effect = Exception("network error")
    assert RemoteOKSource().fetch_listings() == []
