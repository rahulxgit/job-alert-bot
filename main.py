import argparse
"""
Daily job alert bot — entry point.

Pipeline: fetch from independent sources -> dedupe -> keyword pre-filter ->
fill missing/short job descriptions with Crawl4AI (Firecrawl fallback when
configured) -> AI review -> recruiter-email enrichment -> sort -> Sheet/email.
"""
import pandas as pd

import config
from models import JobListing
from utils.logging_setup import get_logger
from utils.run_artifacts import export_stage, export_summary
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
from sources.generic_crawler import crawl_url
from sources.crawl4ai_discovery import Crawl4AIDiscoverySource
from ai.evaluator import prefilter, review_candidates
from enrichment.recruiter_email import enrich_with_emails
from sheets.google_sheets import get_sheet, get_seen_urls, log_new_jobs
from mailer.gmail_client import get_gmail_service, send_email
from mailer.digest import build_email_body

log = get_logger("main")

ALL_SOURCES = [
    LinkedInSource(), GoogleJobsSource(),
    InternshalaSource(), NaukriSource(), WellfoundSource(),
    GreenhouseSource(), LeverSource(), YouTubeSource(), LinkedInPostsSource(),
    ArbeitnowSource(), RemoteOKSource(),
    Crawl4AIDiscoverySource(),
    FirecrawlSource(),
]


def fetch_all() -> tuple:
    """Run every source independently so one failure never blocks the others."""
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
    if not url or "?" not in url:
        return url
    base, _, query = url.partition("?")
    tracking = ("utm_", "ref", "src", "trk", "gclid", "fbclid")
    kept = [pair for pair in query.split("&") if pair and not pair.split("=")[0].lower().startswith(tracking)]
    return f"{base}?{'&'.join(kept)}" if kept else base


def dedupe(listings: list[JobListing]) -> list[JobListing]:
    seen, unique = set(), []
    for listing in listings:
        norm_url = _normalize_url(listing.job_url)
        if norm_url and norm_url not in seen:
            seen.add(norm_url)
            listing.job_url = norm_url
            unique.append(listing)
    return unique


def _source_breakdown(listings: list[JobListing]) -> dict:
    counts: dict = {}
    for listing in listings:
        counts[listing.source] = counts.get(listing.source, 0) + 1
    return counts


def _enrich_descriptions_with_crawl4ai(listings: list[JobListing]) -> list[JobListing]:
    """Fill only missing/short descriptions with bounded generic crawling.

    Crawl4AI is deliberately not used for every listing: JobSpy and the
    dedicated sources already return descriptions for most jobs. This keeps
    browser work bounded while making Crawl4AI the default generic scraper.
    In ``auto`` mode, generic_crawler falls back to Firecrawl if available.
    """
    max_pages = max(0, int(config.CRAWL4AI_MAX_DETAIL_PAGES))
    min_chars = max(0, int(config.CRAWL4AI_MIN_DESCRIPTION_CHARS))
    candidates = [
        listing for listing in listings
        if listing.job_url and len((listing.description or "").strip()) < min_chars
    ][:max_pages]

    if not candidates:
        return listings

    log.info(
        "[Crawl4AI] Enriching %s/%s listings with bounded generic crawling",
        len(candidates),
        len(listings),
    )
    for listing in candidates:
        try:
            enriched = crawl_url(
                listing.job_url,
                title=listing.title,
                company=listing.company,
                location=listing.location,
            )
            if enriched and len((enriched.description or "").strip()) > len((listing.description or "").strip()):
                listing.description = enriched.description
                if not listing.company:
                    listing.company = enriched.company
                if not listing.location:
                    listing.location = enriched.location
                log.info("[Crawl4AI] Enriched: %s", listing.job_url)
        except Exception as exc:
            log.warning("[Crawl4AI] Enrichment failed for %s: %s", listing.job_url, exc)
    return listings


def _export(stage: str, listings: list[JobListing], **metadata) -> None:
    try:
        path = export_stage(stage, listings, metadata=metadata)
        log.info("[Artifacts] %s: %s jobs -> %s", stage, len(listings), path)
    except Exception as exc:
        # Artifact export must never become a new reason for the production job to fail.
        log.warning("[Artifacts] failed to export %s: %s", stage, exc)


def run_pipeline(dry_run: bool = False):
    log.info("Fetching from all sources...")
    all_listings, source_counts = fetch_all()
    _export("raw-listings", all_listings, source_counts=source_counts)

    all_listings = dedupe(all_listings)
    log.info(f"Pulled {len(all_listings)} raw listings total")
    log.info(f"  by source: {source_counts}")
    _export("deduped-listings", all_listings, source_counts=source_counts)

    all_listings = _enrich_descriptions_with_crawl4ai(all_listings)
    _export("enriched-listings", all_listings, source_counts=source_counts)

    shortlist = prefilter(all_listings)
    log.info(f"{len(shortlist)} passed the keyword pre-filter (sent for AI review)")
    log.info(f"  by source: {_source_breakdown(shortlist)}")
    _export("prefilter-shortlist", shortlist, source_counts=_source_breakdown(shortlist))

    if not shortlist:
        export_summary({"status": "completed_no_shortlist", "source_counts": source_counts, "shortlist_count": 0})
        log.info("Nothing to review — no matches today.")
        gmail = get_gmail_service()
        if not dry_run: send_email(gmail, build_email_body([], source_counts), 0)
        return

    sheet = get_sheet()
    seen_urls = get_seen_urls(sheet)
    unseen = [l for l in shortlist if l.job_url not in seen_urls]
    log.info(f"{len(unseen)} of those are new (not already logged)")
    _export("new-unseen-listings", unseen, seen_count=len(seen_urls))

    if not unseen:
        export_summary({"status": "completed_no_new_jobs", "source_counts": source_counts, "shortlist_count": len(shortlist), "unseen_count": 0})
        log.info("Everything in the shortlist was already logged — nothing new to review.")
        gmail = get_gmail_service()
        if not dry_run: send_email(gmail, build_email_body([], source_counts), 0)
        return

    reviewed = review_candidates(unseen)
    log.info(f"{len(reviewed)} passed AI fit review (score >= {config.LLM_FIT_THRESHOLD})")
    log.info(f"  by source: {_source_breakdown(reviewed)}")
    _export("ai-reviewed", reviewed, threshold=config.LLM_FIT_THRESHOLD)

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

    reviewed.sort(key=lambda l: (bool(l.recruiter_email), l.fit_score), reverse=True)
    # This is intentionally written immediately before the Sheets call so a Sheets
    # failure leaves the exact would-have-been-written rows in the Actions artifact.
    _export("final-reviewed", reviewed, recruiter_email_count=found_count)

    export_summary({
        "status": "ready_for_persistence",
        "source_counts": source_counts,
        "shortlist_count": len(shortlist),
        "unseen_count": len(unseen),
        "ai_reviewed_count": len(reviewed),
        "recruiter_email_count": found_count,
    })

    if not dry_run:
        log_new_jobs(sheet, reviewed)

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
