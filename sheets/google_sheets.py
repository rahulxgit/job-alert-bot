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


import pathlib

SEEN_CACHE = pathlib.Path("run-artifacts/sheets-seen-cache.json")
PENDING_QUEUE = pathlib.Path("run-artifacts/sheets-pending-queue.json")

def get_seen_urls(sheet) -> set:
    try:
        urls = sheet.col_values(1)
        seen = set(urls[1:])
        SEEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        SEEN_CACHE.write_text(json.dumps(list(seen), ensure_ascii=False))
        return seen
    except Exception as exc:
        log.warning("Google Sheets API failed during get_seen_urls: %s", exc)
        if SEEN_CACHE.exists():
            log.info("Falling back to local seen_urls cache.")
            try:
                return set(json.loads(SEEN_CACHE.read_text(encoding="utf-8")))
            except Exception:
                pass
        log.warning("No local cache available. Returning empty set.")
        return set()

def _load_pending_queue() -> list[list]:
    if not PENDING_QUEUE.exists():
        return []
    try:
        return json.loads(PENDING_QUEUE.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save_pending_queue(rows: list[list]):
    PENDING_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_QUEUE.write_text(json.dumps(rows, ensure_ascii=False))

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
    pending = _load_pending_queue()
    if pending:
        rows = pending + rows
        log.info("Including %s pending rows from previous failed syncs.", len(pending))

    invalid = [
        (index, value)
        for index, row in enumerate(rows)
        for value in row
        if not isinstance(value, (str, int, float))
    ]
    if invalid:
        raise TypeError(f"non-scalar Google Sheets value at row {invalid[0][0]}: {invalid[0][1]!r}")

    log.info("Writing %s normalized job rows to Google Sheets", len(rows))
    try:
        sheet.append_rows(rows, value_input_option="USER_ENTERED")
        if PENDING_QUEUE.exists():
            PENDING_QUEUE.unlink()
    except Exception as exc:
        log.warning("Google Sheets API failed during append_rows: %s. Saving to pending queue.", exc)
        _save_pending_queue(rows)
