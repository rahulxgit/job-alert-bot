import argparse
import time
from datetime import datetime, timezone
"""
Daily job alert bot — entry point.

Pipeline: fetch from independent sources -> dedupe -> keyword pre-filter ->
fill missing/short job descriptions with a bounded Crawl4AI batch -> AI review
-> recruiter-email enrichment -> sort -> Sheet/email.
"""
import os
import pandas as pd

import config
from models import JobListing
from utils.logging_setup import get_logger
from utils.run_artifacts import export_stage, export_summary
from utils.source_health import SourceHealth, build_search_summary, classify_exception, finalize_health, utc_now
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
from sources.crawl4ai import crawl_urls as crawl4ai_urls
from sources.crawl4ai_discovery import Crawl4AIDiscoverySource
from ai.evaluator import prefilter, review_candidates
from ai.admission_controller import admit_candidates
from enrichment.recruiter_email import enrich_with_emails
from sheets.google_sheets import get_sheet, get_seen_urls, log_new_jobs
from mailer.gmail_client import get_gmail_service, send_email
from mailer.digest import build_email_body

log = get_logger("main")

# Crawl4AI Discovery runs first: it's a complete, independent job-search
# source in its own right (crawls board roots with the same canonical
# SEARCH_TERMS-derived signals and extracts job-detail links directly),
# not just a fallback enrichment step for the other sources below.
ALL_SOURCES = [
    Crawl4AIDiscoverySource(),
    LinkedInSource(), GoogleJobsSource(),
    InternshalaSource(), NaukriSource(), WellfoundSource(),
    GreenhouseSource(), LeverSource(), YouTubeSource(), LinkedInPostsSource(),
    ArbeitnowSource(), RemoteOKSource(),
    FirecrawlSource(),
]


def fetch_all() -> tuple[list[JobListing], dict[str, int], dict[str, SourceHealth]]:
    """Run every source independently and record health/coverage metrics."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_listings: list[JobListing] = []
    source_counts: dict[str, int] = {}
    source_health: dict[str, SourceHealth] = {}
    
    for source in ALL_SOURCES:
        source_health[source.name] = SourceHealth(name=source.name, started_at=utc_now())

    def run_source(source):
        health = source_health[source.name]
        source_started = time.monotonic()
        try:
            listings = source.fetch_listings()
            if listings is None:
                listings = []
            health.jobs_found = len(listings)
            return source.name, listings, None, time.monotonic() - source_started
        except Exception as exc:
            return source.name, [], exc, time.monotonic() - source_started

    with ThreadPoolExecutor(max_workers=len(ALL_SOURCES)) as executor:
        futures = {executor.submit(run_source, source): source for source in ALL_SOURCES}
        for future in as_completed(futures):
            source = futures[future]
            health = source_health[source.name]
            try:
                name, listings, exc, duration = future.result()
                if exc:
                    classification = classify_exception(exc)
                    health.errors.append(str(exc))
                    health.error_classification = classification
                    health.http_api_failures = int(classification.startswith("HTTP_"))
                    if classification not in ("NOT_CONFIGURED", "DISABLED"):
                        log.warning("%s raised unexpectedly: classification=%s error=%s", name, classification, exc)
            except Exception as exc:
                name, listings = source.name, []
                duration = 0.0
                health.errors.append(str(exc))
                health.error_classification = classify_exception(exc)

            health.duration_seconds = max(0.0, duration)
            health.finished_at = datetime.now(timezone.utc).isoformat()
            if health.errors:
                if health.error_classification == "NOT_CONFIGURED":
                    health.status = "NOT_CONFIGURED"
                    log.info("%s disabled: missing optional credential", name)
                elif health.error_classification == "DISABLED":
                    health.status = "DISABLED"
                    log.info("%s disabled: explicitly disabled", name)
                elif health.error_classification == "HTTP_429":
                    health.status = "RATE_LIMITED"
                elif health.error_classification == "HTTP_403":
                    health.status = "BLOCKED"
                else:
                    health.status = "FAILED" if not listings else "DEGRADED"
            elif not listings:
                health.status = "NO_RESULTS"
            else:
                health.status = "SUCCESS"

            if health.status not in ("NOT_CONFIGURED", "DISABLED"):
                source_counts[name] = len(listings)
                health.jobs_found = len(listings)
                health.urls_discovered = len(listings)
                all_listings.extend(listings)
                log.info(
                    "%s: %s listings | status=%s | duration=%.2fs | error=%s",
                    name, len(listings), health.status, health.duration_seconds, health.error_classification or "none",
                )

    zero_sources = [name for name, health in source_health.items() if health.enabled and health.jobs_found == 0]
    failed_sources = [name for name, health in source_health.items() if health.status == "FAILED"]
    degraded_sources = [name for name, health in source_health.items() if health.status == "DEGRADED"]
    if zero_sources:
        log.warning(
            "%s enabled sources returned zero jobs: %s. "
            "This may indicate blocking, selector breakage, API failure, or simply no matches.",
            len(zero_sources),
            ", ".join(zero_sources),
        )
    if failed_sources:
        log.warning("%s sources failed but the remaining sources continued: %s", len(failed_sources), ", ".join(failed_sources))
    if degraded_sources:
        log.warning("%s sources returned jobs with errors: %s", len(degraded_sources), ", ".join(degraded_sources))

    return all_listings, source_counts, source_health


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
    """Fill only missing/short descriptions with one bounded Crawl4AI batch."""
    max_pages = max(0, int(config.CRAWL4AI_MAX_DETAIL_PAGES))
    min_chars = max(0, int(config.CRAWL4AI_MIN_DESCRIPTION_CHARS))
    candidates = [
        listing for listing in listings
        if listing.job_url and len((listing.description or "").strip()) < min_chars
    ][:max_pages]

    if not candidates:
        return listings

    log.info(
        "[Crawl4AI] Batch enriching %s/%s listings with bounded generic crawling",
        len(candidates),
        len(listings),
    )
    metadata = {
        listing.job_url: {
            "title": listing.title,
            "company": listing.company,
            "location": listing.location,
        }
        for listing in candidates
    }
    try:
        enriched_rows = crawl4ai_urls(
            [listing.job_url for listing in candidates],
            timeout_seconds=config.CRAWL4AI_TIMEOUT,
            max_concurrency=4,
            metadata=metadata,
        )
    except Exception as exc:
        log.warning("[Crawl4AI] Batch enrichment failed: %s", exc)
        return listings

    enriched_by_url = {row.job_url: row for row in enriched_rows}
    for listing in candidates:
        enriched = enriched_by_url.get(listing.job_url)
        if not enriched:
            continue
        if len((enriched.description or "").strip()) > len((listing.description or "").strip()):
            listing.description = enriched.description
            if not listing.company:
                listing.company = enriched.company
            if not listing.location:
                listing.location = enriched.location
            log.info("[Crawl4AI] Enriched: %s", listing.job_url)
    return listings


def _export(stage: str, listings: list[JobListing], **metadata) -> None:
    try:
        path = export_stage(stage, listings, metadata=metadata)
        log.info("[Artifacts] %s: %s jobs -> %s", stage, len(listings), path)
    except Exception as exc:
        log.warning("[Artifacts] failed to export %s: %s", stage, exc)


def _export_search_summary(*, source_health: dict[str, SourceHealth], raw_count: int, unique_count: int, source_breakdown: dict[str, int], duration_seconds: float, status: str) -> None:
    duplicate_count = max(0, raw_count - unique_count)
    summary = build_search_summary(
        source_health=source_health,
        raw_listings=raw_count,
        unique_listings=unique_count,
        source_breakdown=source_breakdown,
        duplicate_count=duplicate_count,
        duration_seconds=duration_seconds,
        status=status,
    )
    try:
        from pathlib import Path
        import json
        path = Path("run-artifacts") / "search-summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("[Artifacts] search-summary: %s", path)
    except Exception as exc:
        log.warning("[Artifacts] failed to export search summary: %s", exc)


def run_pipeline(dry_run: bool = False):
    search_started = time.monotonic()
    log.info("Fetching from all sources...")
    all_listings, source_counts, source_health = fetch_all()
    raw_count = len(all_listings)
    _export("raw-listings", all_listings, source_counts=source_counts, source_health={name: health.to_dict() for name, health in source_health.items()})

    all_listings = dedupe(all_listings)
    log.info(f"Pulled {len(all_listings)} raw listings total")
    log.info(f"  by source: {source_counts}")
    _export("deduped-listings", all_listings, source_counts=source_counts, source_health={name: health.to_dict() for name, health in source_health.items()})
    _export_search_summary(source_health=source_health, raw_count=raw_count, unique_count=len(all_listings), source_breakdown=_source_breakdown(all_listings), duration_seconds=time.monotonic() - search_started, status="collection_complete")

    all_listings = _enrich_descriptions_with_crawl4ai(all_listings)
    _export("enriched-listings", all_listings, source_counts=source_counts, source_health={name: health.to_dict() for name, health in source_health.items()})

    shortlist = prefilter(all_listings)
    log.info(f"{len(shortlist)} passed the precise pre-filter (AI pool cap {config.MAX_LLM_CANDIDATES})")
    log.info(f"  by source: {_source_breakdown(shortlist)}")
    _export("prefilter-shortlist", shortlist, source_counts=_source_breakdown(shortlist))

    if not shortlist:
        _export_search_summary(source_health=source_health, raw_count=raw_count, unique_count=len(all_listings), source_breakdown=_source_breakdown(all_listings), duration_seconds=time.monotonic() - search_started, status="completed_no_shortlist")
        export_summary({"status": "completed_no_shortlist", "source_counts": source_counts, "shortlist_count": 0})
        log.info("Nothing to review — no matches today.")
        if not dry_run:
            gmail = get_gmail_service()
            send_email(gmail, build_email_body([], source_counts), 0)
        else:
            log.info("Dry run: email not sent.")
        return

    if dry_run:
        seen_urls = []
        log.info("Dry run: skipping Google Sheets seen_urls check.")
    else:
        sheet = get_sheet()
        seen_urls = get_seen_urls(sheet)
        
    unseen = [l for l in shortlist if l.job_url not in seen_urls]
    log.info(f"{len(unseen)} of those are new (not already logged)")
    _export("new-unseen-listings", unseen, seen_count=len(seen_urls))

    if not unseen:
        _export_search_summary(source_health=source_health, raw_count=raw_count, unique_count=len(all_listings), source_breakdown=_source_breakdown(all_listings), duration_seconds=time.monotonic() - search_started, status="completed_no_new_jobs")
        export_summary({"status": "completed_no_new_jobs", "source_counts": source_counts, "shortlist_count": len(shortlist), "unseen_count": 0})
        log.info("Everything in the shortlist was already logged — nothing new to review.")
        if not dry_run:
            gmail = get_gmail_service()
            send_email(gmail, build_email_body([], source_counts), 0)
        else:
            log.info("Dry run: email not sent.")
        return

    from ai.admission_controller import load_deferred_candidates
    previously_deferred = [l for l in load_deferred_candidates() if l.job_url not in seen_urls]
    unseen = previously_deferred + [l for l in unseen if l.job_url not in {d.job_url for d in previously_deferred}]
    admitted, deferred = admit_candidates(unseen)
    log.info(
        "AI admission control: %s admitted / %s unseen; %s deferred",
        len(admitted),
        len(unseen),
        len(deferred),
    )
    _export(
        "ai-admitted-listings",
        admitted,
        admission_limit=os.environ.get("AI_ADMISSION_LIMIT", "unset"),
        deferred_count=len(deferred),
    )

    if admitted:
        try:
            import requests
            log.info("Warming up AI Gateway (may take 90s on cold start)...")
            requests.get(config.AI_GATEWAY_URL, timeout=90)
            log.info("AI Gateway warmed up.")
        except Exception as exc:
            log.warning("AI Gateway warmup failed or timed out: %s", exc)

    budget_seconds = max(1, int(getattr(config, "LLM_EVALUATION_BUDGET_SECONDS", 2700)))
    # The budget should start from the script's execution, not when AI starts,
    # to prevent the overall GitHub Action from hitting its hard timeout.
    global_deadline = search_started + budget_seconds
    reviewed = review_candidates(admitted, deadline=global_deadline)
    log.info(f"{len(reviewed)} passed AI fit review (score >= {config.LLM_FIT_THRESHOLD})")
    log.info(f"  by source: {_source_breakdown(reviewed)}")
    _export("ai-reviewed", reviewed, threshold=config.LLM_FIT_THRESHOLD, admitted_count=len(admitted), deferred_count=len(deferred))

    reviewed_urls = {l.job_url for l in reviewed}
    if len(reviewed_urls) != len(reviewed):
        seen_dedup, deduped = set(), []
        for l in reviewed:
            if l.job_url not in seen_dedup:
                seen_dedup.add(l.job_url)
                deduped.append(l)
        reviewed = deduped
    if dry_run:
        latest_seen = []
    else:
        latest_seen = get_seen_urls(sheet)
    reviewed = [l for l in reviewed if l.job_url not in latest_seen]

    log.info("Looking for recruiter/company emails on the final shortlist...")
    reviewed = enrich_with_emails(reviewed)
    found_count = sum(1 for l in reviewed if l.recruiter_email)
    log.info(f"  found an email for {found_count}/{len(reviewed)} jobs")

    reviewed.sort(key=lambda l: (bool(l.recruiter_email), l.fit_score), reverse=True)
    _export("final-reviewed", reviewed, recruiter_email_count=found_count, admitted_count=len(admitted), deferred_count=len(deferred))

    _export_search_summary(source_health=source_health, raw_count=raw_count, unique_count=len(all_listings), source_breakdown=_source_breakdown(all_listings), duration_seconds=time.monotonic() - search_started, status="ready_for_persistence")
    export_summary({
        "status": "ready_for_persistence",
        "source_counts": source_counts,
        "shortlist_count": len(shortlist),
        "unseen_count": len(unseen),
        "ai_admitted_count": len(admitted),
        "ai_deferred_count": len(deferred),
        "ai_reviewed_count": len(reviewed),
        "recruiter_email_count": found_count,
    })

    if not dry_run:
        log_new_jobs(sheet, reviewed)

    body = build_email_body(reviewed, source_counts)
    if not dry_run:
        gmail = get_gmail_service()
        send_email(gmail, body, len(reviewed))
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
