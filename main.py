import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
"""
Daily job alert bot — entry point.

Pipeline: fetch from independent sources -> canonicalize/dedupe -> bounded Crawl4AI
richment -> keyword pre-filter -> quality ranking -> AI review -> recruiter-email
enrichment -> sort -> Sheet/email.
"""
import pandas as pd

import config
from models import JobListing
from utils.job_quality import canonical_url, deduplicate_jobs, quality_summary, rank_candidates
from utils.logging_setup import get_logger
from utils.run_artifacts import export_stage, export_summary
from utils.source_health import SourceHealth, build_search_summary, classify_exception, utc_now
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
from sources.crawl4ai import crawl_urls as crawl4ai_urls
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
    Crawl4AIDiscoverySource(), FirecrawlSource(),
]


def fetch_all() -> tuple[list[JobListing], dict[str, int], dict[str, SourceHealth]]:
    all_listings: list[JobListing] = []
    source_counts: dict[str, int] = {}
    source_health: dict[str, SourceHealth] = {}
    for source in ALL_SOURCES:
        health = SourceHealth(name=source.name, started_at=utc_now())
        source_health[source.name] = health
        started = time.monotonic()
        try:
            listings = source.fetch_listings() or []
            health.jobs_found = len(listings)
        except Exception as exc:
            classification = classify_exception(exc)
            health.errors.append(str(exc))
            health.error_classification = classification
            health.http_api_failures = int(classification.startswith("HTTP_"))
            listings = []
            log.warning("%s raised: classification=%s error=%s", source.name, classification, exc)
        health.duration_seconds = max(0.0, time.monotonic() - started)
        health.finished_at = datetime.now(timezone.utc).isoformat()
        if health.errors:
            health.status = "FAILED" if not listings else "DEGRADED"
        elif not listings:
            health.status = "HEALTHY"
            health.error_classification = "NO_RESULTS"
        else:
            health.status = "HEALTHY"
        source_counts[source.name] = len(listings)
        health.jobs_found = len(listings)
        health.urls_discovered = len(listings)
        all_listings.extend(listings)
    zero_sources = [name for name, health in source_health.items() if health.enabled and health.jobs_found == 0]
    if zero_sources:
        log.warning("%s enabled sources returned zero jobs: %s", len(zero_sources), ", ".join(zero_sources))
    return all_listings, source_counts, source_health


def _source_breakdown(listings: list[JobListing]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for listing in listings:
        counts[listing.source] = counts.get(listing.source, 0) + 1
    return counts


def _enrich_descriptions_with_crawl4ai(listings: list[JobListing]) -> list[JobListing]:
    max_pages = max(0, int(config.CRAWL4AI_MAX_DETAIL_PAGES))
    min_chars = max(0, int(config.CRAWL4AI_MIN_DESCRIPTION_CHARS))
    candidates = [listing for listing in listings if listing.job_url and len((listing.description or "").strip()) < min_chars][:max_pages]
    if not candidates:
        return listings
    metadata = {listing.job_url: {"title": listing.title, "company": listing.company, "location": listing.location} for listing in candidates}
    try:
        enriched_rows = crawl4ai_urls([listing.job_url for listing in candidates], timeout_seconds=config.CRAWL4AI_TIMEOUT, max_concurrency=4, metadata=metadata)
    except Exception as exc:
        log.warning("[Crawl4AI] Batch enrichment failed: %s", exc)
        return listings
    enriched_by_url = {row.job_url: row for row in enriched_rows}
    for listing in candidates:
        enriched = enriched_by_url.get(listing.job_url)
        if enriched and len((enriched.description or "").strip()) > len((listing.description or "").strip()):
            listing.description = enriched.description
            if not listing.company:
                listing.company = enriched.company
            if not listing.location:
                listing.location = enriched.location
    return listings


def _export(stage: str, listings: list[JobListing], **metadata) -> None:
    try:
        path = export_stage(stage, listings, metadata=metadata)
        log.info("[Artifacts] %s: %s jobs -> %s", stage, len(listings), path)
    except Exception as exc:
        log.warning("[Artifacts] failed to export %s: %s", stage, exc)


def _export_search_summary(*, source_health: dict[str, SourceHealth], raw_count: int, unique_count: int, source_breakdown: dict[str, int], duration_seconds: float, status: str) -> None:
    summary = build_search_summary(source_health=source_health, raw_listings=raw_count, unique_listings=unique_count, source_breakdown=source_breakdown, duplicate_count=max(0, raw_count - unique_count), duration_seconds=duration_seconds, status=status)
    try:
        path = Path("run-artifacts") / "search-summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("[Artifacts] failed to export search summary: %s", exc)


def _export_quality_summary(summary: dict) -> None:
    try:
        path = Path("run-artifacts") / "job-quality-summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("[Artifacts] job-quality-summary: %s", path)
    except Exception as exc:
        log.warning("[Artifacts] failed to export job quality summary: %s", exc)


def run_pipeline(dry_run: bool = False):
    search_started = time.monotonic()
    log.info("Fetching from all sources...")
    all_listings, source_counts, source_health = fetch_all()
    raw_count = len(all_listings)
    _export("raw-listings", all_listings, source_counts=source_counts, source_health={name: health.to_dict() for name, health in source_health.items()})

    all_listings, duplicates_removed = deduplicate_jobs(all_listings)
    for listing in all_listings:
        listing.job_url = canonical_url(listing.job_url)
    log.info("Normalized/deduplicated to %s unique jobs; removed %s duplicates", len(all_listings), duplicates_removed)
    _export("deduped-listings", all_listings, duplicates_removed=duplicates_removed, source_counts=source_counts)

    all_listings = _enrich_descriptions_with_crawl4ai(all_listings)
    _export("enriched-listings", all_listings, source_counts=source_counts)

    eligible = prefilter(all_listings)
    ranked = rank_candidates(eligible)
    shortlist = ranked[:config.MAX_LLM_CANDIDATES]
    quality = quality_summary(raw_count, all_listings, eligible, shortlist, duplicates_removed)
    _export_quality_summary(quality)
    _export("prefilter-shortlist", shortlist, source_counts=_source_breakdown(shortlist), quality_summary=quality)
    _export_search_summary(source_health=source_health, raw_count=raw_count, unique_count=len(all_listings), source_breakdown=_source_breakdown(all_listings), duration_seconds=time.monotonic() - search_started, status="collection_complete")
    log.info("%s eligible jobs; top %s selected for AI (MAX_LLM_CANDIDATES=%s)", len(eligible), len(shortlist), config.MAX_LLM_CANDIDATES)

    if not shortlist:
        export_summary({"status": "completed_no_shortlist", "source_counts": source_counts, "shortlist_count": 0, "quality_summary": quality})
        log.info("Nothing to review — no matches today.")
        if not dry_run:
            gmail = get_gmail_service()
            send_email(gmail, build_email_body([], source_counts), 0)
        return

    sheet = get_sheet()
    seen_urls = {canonical_url(url) for url in get_seen_urls(sheet)}
    unseen = [listing for listing in shortlist if canonical_url(listing.job_url) not in seen_urls]
    _export("new-unseen-listings", unseen, seen_count=len(seen_urls), quality_summary=quality)
    log.info("%s of those are new (not already logged)", len(unseen))

    if not unseen:
        export_summary({"status": "completed_no_new_jobs", "source_counts": source_counts, "shortlist_count": len(shortlist), "unseen_count": 0, "quality_summary": quality})
        log.info("Everything in the shortlist was already logged — nothing new to review.")
        if not dry_run:
            gmail = get_gmail_service()
            send_email(gmail, build_email_body([], source_counts), 0)
        return

    reviewed = review_candidates(unseen)
    log.info("%s passed AI fit review (score >= %s)", len(reviewed), config.LLM_FIT_THRESHOLD)
    _export("ai-reviewed", reviewed, threshold=config.LLM_FIT_THRESHOLD, quality_summary=quality)

    deduped_reviewed: dict[str, JobListing] = {}
    for listing in reviewed:
        key = canonical_url(listing.job_url)
        if key not in deduped_reviewed:
            deduped_reviewed[key] = listing
    latest_seen = {canonical_url(url) for url in get_seen_urls(sheet)}
    reviewed = [listing for key, listing in deduped_reviewed.items() if key not in latest_seen]

    reviewed = enrich_with_emails(reviewed)
    found_count = sum(1 for listing in reviewed if listing.recruiter_email)
    reviewed.sort(key=lambda listing: (bool(listing.recruiter_email), listing.fit_score), reverse=True)
    _export("final-reviewed", reviewed, recruiter_email_count=found_count, quality_summary=quality)

    _export_search_summary(source_health=source_health, raw_count=raw_count, unique_count=len(all_listings), source_breakdown=_source_breakdown(all_listings), duration_seconds=time.monotonic() - search_started, status="ready_for_persistence")
    export_summary({"status": "ready_for_persistence", "source_counts": source_counts, "shortlist_count": len(shortlist), "unseen_count": len(unseen), "ai_reviewed_count": len(reviewed), "recruiter_email_count": found_count, "quality_summary": quality})
    if not dry_run:
        log_new_jobs(sheet, reviewed)
        gmail = get_gmail_service()
        send_email(gmail, build_email_body(reviewed, source_counts), len(reviewed))
        log.info("Email sent.")
    else:
        log.info("Dry run: email not sent.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily job alert bot")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending emails or updating google sheets")
    args = parser.parse_args()
    if not args.dry_run:
        config.validate()
    run_pipeline(dry_run=args.dry_run)
