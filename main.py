import argparse
"""
Daily job alert bot — entry point.

Pipeline: fetch from 10 independent sources (each isolated — one failing
never blocks the others) -> dedupe -> keyword pre-filter -> AI review
(Gemini, falling back to a self-hosted gateway) -> recruiter-email
enrichment -> sort (contactable jobs first) -> log to Sheet -> email digest.

Run manually with: python -u main.py
Runs automatically daily via .github/workflows/job-alerts.yml
"""
import pandas as pd

import config
from models import JobListing
from utils.logging_setup import get_logger
from sources.linkedin import LinkedInSource
from sources.google import GoogleJobsSource
from sources.internshala import InternshalaSource
from sources.naukri import NaukriSource
from sources.wellfound import WellfoundSource
from sources.greenhouse import GreenhouseSource
from sources.lever import LeverSource
from sources.youtube import YouTubeSource
from sources.linkedin_posts import LinkedInPostsSource
from sources.arbeitnow import ArbeitnowSource
from sources.remoteok import RemoteOKSource
from sources.firecrawl import FirecrawlSource
from ai.evaluator import prefilter, review_candidates
from enrichment.recruiter_email import enrich_with_emails
from sheets.google_sheets import get_sheet, get_seen_urls, log_new_jobs
from mailer.gmail_client import get_gmail_service, send_email
from mailer.digest import build_email_body

log = get_logger("main")

# Every source here is independent — this list is the only place that
# needs editing to add/remove a source. Order doesn't matter functionally,
# only for log readability.
ALL_SOURCES = [
    LinkedInSource(), GoogleJobsSource(),
    InternshalaSource(), NaukriSource(), WellfoundSource(),
    GreenhouseSource(), LeverSource(), YouTubeSource(), LinkedInPostsSource(),
    ArbeitnowSource(), RemoteOKSource(), FirecrawlSource(),
]


def fetch_all() -> tuple:
    """Runs every source, isolating failures so one broken source can
    never take down the rest. Returns (all_listings, source_counts)."""
    all_listings: list[JobListing] = []
    source_counts: dict = {}

    for source in ALL_SOURCES:
        try:
            listings = source.fetch_listings()
        except Exception as exc:
            log.warning(f"{source.name} raised unexpectedly (should have caught internally): {exc}")
            listings = []
        log.info(f"{source.name}: {len(listings)} listings")
        source_counts[source.name] = len(listings)
        all_listings.extend(listings)

    return all_listings, source_counts



def _normalize_url(url: str) -> str:
    """Strips common tracking params so the same job found via two
    different query strings still dedupes cleanly."""
    if not url or "?" not in url:
        return url
    base, _, query = url.partition("?")
    TRACKING_PARAM_PREFIXES = ("utm_", "ref", "src", "trk", "gclid", "fbclid")
    kept = [
        pair for pair in query.split("&")
        if pair and not pair.split("=")[0].lower().startswith(TRACKING_PARAM_PREFIXES)
    ]
    return f"{base}?{'&'.join(kept)}" if kept else base

def dedupe(listings: list[JobListing]) -> list[JobListing]:
    seen, unique = set(), []
    for listing in listings:
        norm_url = _normalize_url(listing.job_url)
        if norm_url and norm_url not in seen:
            seen.add(norm_url)
            # Retain normalized url in the listing to avoid downstream duplication
            listing.job_url = norm_url
            unique.append(listing)
    return unique



def _source_breakdown(listings: list[JobListing]) -> dict:
    counts: dict = {}
    for listing in listings:
        counts[listing.source] = counts.get(listing.source, 0) + 1
    return counts


def run_pipeline(dry_run: bool = False):
    log.info("Fetching from all sources...")
    all_listings, source_counts = fetch_all()
    all_listings = dedupe(all_listings)
    log.info(f"Pulled {len(all_listings)} raw listings total")
    log.info(f"  by source: {source_counts}")

    shortlist = prefilter(all_listings)
    log.info(f"{len(shortlist)} passed the keyword pre-filter (sent for AI review)")
    log.info(f"  by source: {_source_breakdown(shortlist)}")

    if not shortlist:
        log.info("Nothing to review — no matches today.")
        gmail = get_gmail_service()
        if not dry_run: send_email(gmail, build_email_body([], source_counts), 0)
        return

    sheet = get_sheet()
    seen_urls = get_seen_urls(sheet)
    unseen = [l for l in shortlist if l.job_url not in seen_urls]
    log.info(f"{len(unseen)} of those are new (not already logged)")

    if not unseen:
        log.info("Everything in the shortlist was already logged — nothing new to review.")
        gmail = get_gmail_service()
        if not dry_run: send_email(gmail, build_email_body([], source_counts), 0)
        return

    reviewed = review_candidates(unseen)
    log.info(f"{len(reviewed)} passed AI fit review (score >= {config.LLM_FIT_THRESHOLD})")
    log.info(f"  by source: {_source_breakdown(reviewed)}")

    # Defensive re-check right before writing — insurance against an
    # overlapping run (the workflow's concurrency guard should prevent
    # this, but this is cheap and catches any edge case it misses).
    reviewed_urls = {l.job_url for l in reviewed}
    if len(reviewed_urls) != len(reviewed):
        seen_dedup, deduped = set(), []
        for l in reviewed:
            if l.job_url not in seen_dedup:
                seen_dedup.add(l.job_url)
                deduped.append(l)
        reviewed = deduped
    latest_seen = get_seen_urls(sheet)
    reviewed = [l for l in reviewed if l.job_url not in latest_seen]

    log.info("Looking for recruiter/company emails on the final shortlist...")
    reviewed = enrich_with_emails(reviewed)
    found_count = sum(1 for l in reviewed if l.recruiter_email)
    log.info(f"  found an email for {found_count}/{len(reviewed)} jobs")

    # Prioritize outreach-ready jobs: contactable first, fit score breaks
    # ties. Fit is still the quality gate — this only reorders what
    # already passed review.
    reviewed.sort(key=lambda l: (bool(l.recruiter_email), l.fit_score), reverse=True)

    if not dry_run: log_new_jobs(sheet, reviewed)

    gmail = get_gmail_service()
    body = build_email_body(reviewed, source_counts)
    if not dry_run: send_email(gmail, body, len(reviewed))
    log.info("Email sent.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily job alert bot")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending emails or updating google sheets")
    args = parser.parse_args()

    if not args.dry_run:
        config.validate()
    run_pipeline(dry_run=args.dry_run)
