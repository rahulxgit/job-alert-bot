"""Google Sheets logging — dedup log so the same job never gets emailed
twice. Sheet columns (in write order): URL, Title, Company, Location,
Fit Score, Reason, Date Added, Email, Source, Applied (Applied is
maintained manually by the user, never written by this code)."""
import json
from datetime import datetime
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
    return set(urls[1:])  # skip header row


def log_new_jobs(sheet, listings: list[JobListing]):
    if not listings:
        return
    rows = [
        [
            listing.job_url, listing.title, listing.company, listing.location,
            int(listing.fit_score), listing.reason,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            listing.recruiter_email, listing.source or "Unknown",
        ]
        for listing in listings
    ]
    sheet.append_rows(rows, value_input_option="USER_ENTERED")
