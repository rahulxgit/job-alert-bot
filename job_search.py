"""
Daily job alert bot.

Pulls fresher/SDE-1 listings from Indeed, LinkedIn and Naukri (via jobspy),
scores each one against my profile, mails the top matches, and logs
everything to a Google Sheet so I don't get the same listing twice.

Run manually with:  python job_search.py
Runs automatically every day at 8 AM IST via .github/workflows/job-alerts.yml
"""

import base64
import os
from datetime import datetime, timedelta
from email.mime.text import MIMEText

import gspread
import pandas as pd
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from jobspy import scrape_jobs

# ---------------------------------------------------------------------------
# Config — tweak these as the search evolves
# ---------------------------------------------------------------------------

SEARCH_TERMS = [
    "SDE 1",
    "Software Development Engineer",
    "Full Stack Developer",
    "Backend Developer",
]

LOCATIONS = ["Bengaluru, India", "India"]

SITES = ["indeed", "linkedin"]

RESULTS_PER_SITE = 30
HOURS_OLD = 24  # only look at listings posted in the last day

# Keywords pulled from my resume/tech stack — used to score relevance
PROFILE_KEYWORDS = [
    "react", "next.js", "nextjs", "node", "express", "typescript", "javascript",
    "mongodb", "postgresql", "prisma", "mysql", "supabase", "firebase",
    "rest api", "mern", "full stack", "fullstack", "sde", "fresher",
    "0-2 years", "0-1 years", "entry level", "graduate", "ai agents",
    "rag", "llm", "docker", "git", "ci/cd", "python", "java",
]

# Companies I'm specifically targeting
PRIORITY_COMPANIES = [
    "razorpay", "sarvam", "groww", "meesho", "zepto", "cred", "swiggy",
    "zomato", "flipkart", "postman", "browserstack", "freshworks",
]

SHEET_NAME = "Job Search Tracker"
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

GMAIL_TO = os.environ["ALERT_EMAIL_TO"]


# ---------------------------------------------------------------------------
# Scraping + scoring
# ---------------------------------------------------------------------------

def fetch_jobs() -> pd.DataFrame:
    all_results = []
    for term in SEARCH_TERMS:
        for location in LOCATIONS:
            try:
                df = scrape_jobs(
                    site_name=SITES,
                    search_term=term,
                    location=location,
                    results_wanted=RESULTS_PER_SITE,
                    hours_old=HOURS_OLD,
                    country_indeed="India",
                )
                if df is not None and not df.empty:
                    all_results.append(df)
            except Exception as exc:
                print(f"[warn] scrape failed for '{term}' in '{location}': {exc}")

    if not all_results:
        return pd.DataFrame()

    combined = pd.concat(all_results, ignore_index=True)
    combined.drop_duplicates(subset=["job_url"], inplace=True)
    return combined


def score_job(row: pd.Series) -> int:
    text = f"{row.get('title', '')} {row.get('description', '')} {row.get('company', '')}".lower()
    score = sum(kw in text for kw in PROFILE_KEYWORDS)
    if any(company in text for company in PRIORITY_COMPANIES):
        score += 5
    return score


def filter_and_rank(df: pd.DataFrame, min_score: int = 3) -> pd.DataFrame:
    if df.empty:
        return df
    df["match_score"] = df.apply(score_job, axis=1)
    df = df[df["match_score"] >= min_score]
    df.sort_values("match_score", ascending=False, inplace=True)
    return df


# ---------------------------------------------------------------------------
# Google Sheets — dedup log
# ---------------------------------------------------------------------------

def get_sheet():
    creds = ServiceAccountCredentials.from_service_account_info(
        eval(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1


def get_seen_urls(sheet) -> set:
    urls = sheet.col_values(1)
    return set(urls[1:])  # skip header row


def log_new_jobs(sheet, df: pd.DataFrame):
    if df.empty:
        return
    rows = [
        [
            row.get("job_url", ""),
            row.get("title", ""),
            row.get("company", ""),
            row.get("location", ""),
            row.get("match_score", ""),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ]
        for _, row in df.iterrows()
    ]
    sheet.append_rows(rows, value_input_option="USER_ENTERED")


# ---------------------------------------------------------------------------
# Gmail — send the digest
# ---------------------------------------------------------------------------

def get_gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    return build("gmail", "v1", credentials=creds)


def build_email_body(df: pd.DataFrame) -> str:
    if df.empty:
        return "No new matching listings today."

    lines = [f"{len(df)} new job(s) matched today:\n"]
    for _, row in df.iterrows():
        lines.append(
            f"- {row.get('title')} @ {row.get('company')} "
            f"({row.get('location')}) — score {row.get('match_score')}\n"
            f"  {row.get('job_url')}\n"
        )
    return "\n".join(lines)


def send_email(service, body: str, job_count: int):
    subject = f"Job Alert — {job_count} new match(es), {datetime.now().strftime('%d %b')}"
    message = MIMEText(body)
    message["to"] = GMAIL_TO
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Fetching jobs...")
    raw_jobs = fetch_jobs()
    print(f"Pulled {len(raw_jobs)} raw listings")

    ranked = filter_and_rank(raw_jobs)
    print(f"{len(ranked)} listings passed the relevance filter")

    if ranked.empty:
        print("No listings matched today — nothing to log or email.")
        return

    sheet = get_sheet()
    seen = get_seen_urls(sheet)
    new_jobs = ranked[~ranked["job_url"].isin(seen)]
    print(f"{len(new_jobs)} of those are new")

    log_new_jobs(sheet, new_jobs)

    gmail = get_gmail_service()
    body = build_email_body(new_jobs)
    send_email(gmail, body, len(new_jobs))
    print("Email sent.")


if __name__ == "__main__":
    main()
