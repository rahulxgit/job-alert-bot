"""Google Sheets logging with strict scalar cell normalization."""
import json
from datetime import datetime
from typing import Any

import gspread
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

import config
from models import JobListing
from utils.logging_setup import get_logger

log = get_logger("sheets")


def get_sheet():
    creds = ServiceAccountCredentials.from_service_account_info(
        json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(creds)
    return client.open_by_key(config.GOOGLE_SHEET_ID).sheet1


def get_seen_urls(sheet) -> set:
    urls = sheet.col_values(1)
    return set(urls[1:])


def _sheet_value(value: Any) -> str | int | float:
    """Convert arbitrary Python values into Google Sheets scalar values."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (str, int, float)):
        return value
    if isinstance(value, (list, tuple, set)):
        return "; ".join(_sheet_value(item).__str__() for item in value if item is not None)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _listing_to_sheet_row(listing: JobListing) -> list[str | int | float]:
    return [
        _sheet_value(listing.job_url),
        _sheet_value(listing.title),
        _sheet_value(listing.company),
        _sheet_value(listing.location),
        _sheet_value(int(listing.fit_score)),
        _sheet_value(listing.fit_tier),
        _sheet_value(listing.reason),
        _sheet_value(listing.gaps),
        _sheet_value(listing.role_match),
        _sheet_value(listing.experience_match),
        _sheet_value(listing.technical_match),
        _sheet_value(listing.project_match),
        _sheet_value(listing.education_match),
        _sheet_value(listing.location_match),
        _sheet_value(datetime.now().strftime("%Y-%m-%d %H:%M")),
        _sheet_value(listing.recruiter_email),
        _sheet_value(listing.source or "Unknown"),
    ]


def log_new_jobs(sheet, listings: list[JobListing]):
    if not listings:
        return

    rows = [_listing_to_sheet_row(listing) for listing in listings]
    invalid = [
        (index, value)
        for index, row in enumerate(rows)
        for value in row
        if not isinstance(value, (str, int, float))
    ]
    if invalid:
        raise TypeError(f"non-scalar Google Sheets value at row {invalid[0][0]}: {invalid[0][1]!r}")

    log.info("Writing %s normalized job rows to Google Sheets", len(rows))
    sheet.append_rows(rows, value_input_option="USER_ENTERED")
