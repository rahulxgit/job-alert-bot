import os
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

"""Job-fit evaluation driven by the canonical master profile."""

import config
from models import FitVerdict, JobListing
from ai.gemini_provider import GeminiProvider
from ai.gateway_provider import GatewayProvider
from ai.profile import build_candidate_profile
from ai.metrics import MetricsCoordinator
from ai.checkpoint import CHECKPOINT_VERSION, compatible, evaluation_key, profile_hash, checkpoint_identity
from ai.provider_limiter import ProviderBackoff
from ai.state import EvaluationState, QUEUED, EVALUATING, EVALUATED, PASSED, REJECTED, RETRYABLE_ERROR, PERMANENT_ERROR, DEADLINE_EXCEEDED
from ai.state_store import AIStateStore
from ai.state_migration import migrate_legacy_progress, migrate_legacy_retry_jobs
from utils.logging_setup import get_logger

log = get_logger("evaluator")
_gemini = GeminiProvider()
_gateway = GatewayProvider()
_candidate_profile = None
FAILED_AI_JOBS_PATH = Path("failed-ai-jobs.json")
AI_PROGRESS_PATH = Path("run-artifacts/ai-progress.json")
AI_PROGRESS_VERSION = CHECKPOINT_VERSION
AI_MAX_ATTEMPTS_PER_CANDIDATE = max(1, int(getattr(config, "AI_EVALUATION_MAX_ATTEMPTS_PER_CANDIDATE", 3)))
AI_RETRY_DELAY_SECONDS = max(1.0, float(getattr(config, "AI_EVALUATION_RETRY_DELAY_SECONDS", 15)))
AI_MAX_RETRY_DELAY_SECONDS = max(AI_RETRY_DELAY_SECONDS, float(getattr(config, "AI_EVALUATION_MAX_RETRY_DELAY_SECONDS", 60)))
_gemini_backoff = ProviderBackoff()
_gateway_backoff = ProviderBackoff()


def _profile() -> str:
    global _candidate_profile
    if _candidate_profile is None:
        _candidate_profile = build_candidate_profile()
    return _candidate_profile

# ... unchanged evaluator implementation above omitted intentionally ...


def _legacy_state_store():
    """Build the unified store and import legacy files only when necessary."""
    state_path = AI_PROGRESS_PATH.with_name("ai-state.json")
    store = AIStateStore(state_path)
    if store.load():
        return store

    progress = _load_ai_progress()
    retry_payload: dict = {}
    if FAILED_AI_JOBS_PATH.exists():
        try:
            raw = json.loads(FAILED_AI_JOBS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                retry_payload = raw
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            retry_payload = {}

    migrated = migrate_legacy_progress(progress) + migrate_legacy_retry_jobs(
        retry_payload.get("jobs", []) if isinstance(retry_payload, dict) else []
    )
    if migrated:
        deduped: dict[str, EvaluationState] = {}
        for state in migrated:
            existing = deduped.get(state.job_url)
            if existing is None or state.status in {RETRYABLE_ERROR, DEADLINE_EXCEEDED}:
                deduped[state.job_url] = state
        store.replace_all(deduped.values())
    return store


def _legacy_run_completed() -> bool:
    """Return whether the legacy progress file explicitly marks the prior run complete."""
    if not AI_PROGRESS_PATH.exists():
        return False
    try:
        payload = json.loads(AI_PROGRESS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("status") == "completed"


def review_candidates(listings: list[JobListing], deadline: float | None = None) -> list[JobListing]:
    """Review jobs with one authoritative per-job state machine."""
    if deadline is None:
        budget_seconds = max(1, int(getattr(config, "LLM_EVALUATION_BUDGET_SECONDS", 2700)))
        deadline = time.monotonic() + budget_seconds

    store = _legacy_state_store()
    states = store.load()
    retry_jobs = []
    retry_urls = set()
    for job in listings:
        state = states.get(job.job_url)
        if state and state.status in {RETRYABLE_ERROR, DEADLINE_EXCEEDED, EVALUATING, QUEUED}:
            retry_jobs.append(job)
            retry_urls.add(job.job_url)

    progress = _load_ai_progress()
    profile_text = _profile()
    profile_digest = profile_hash(profile_text)
    candidate_urls = [job.job_url for job in listings if job.job_url]
    progress_identity = checkpoint_identity(candidate_urls[:config.MAX_LLM_CANDIDATES], profile_digest)

    if progress and not compatible(progress, candidate_urls[:config.MAX_LLM_CANDIDATES], profile_digest):
        log.warning("Ignoring incompatible legacy AI checkpoint; unified state is authoritative")
        progress = {}

    resumed_jobs = []
    allow_terminal_resume = not _legacy_run_completed()
    for job in listings:
        state = states.get(job.job_url)
        expected_key = evaluation_key(job.job_url, job.description, profile_digest)
        if allow_terminal_resume and state and state.status in {PASSED, REJECTED, EVALUATED} and state.evaluation_key == expected_key and state.verdict:
            verdict = FitVerdict(**{k: v for k, v in state.verdict.items() if k in {"fit_score", "is_fresher_appropriate", "reason", "hit_rate_limit", "role_match", "experience_match", "technical_match", "project_match", "education_match", "location_match", "company_quality", "decision", "why", "gaps"}})
            _apply_verdict(job, verdict)
            resumed_jobs.append(job)

    resumed_urls = {job.job_url for job in resumed_jobs}
    new_jobs = [job for job in listings if job.job_url and job.job_url not in resumed_urls and job.job_url not in retry_urls]
    ordered_jobs = retry_jobs + new_jobs[:config.MAX_LLM_CANDIDATES]

    passed = [job for job in resumed_jobs if job.fit_score >= config.LLM_FIT_THRESHOLD and job.fresher_appropriate]
    coordinator = MetricsCoordinator(AI_PROGRESS_PATH, metrics_enabled=getattr(config, "AI_METRICS_ENABLED", True))
    coordinator.save_progress({
        **(progress or {}),
        **progress_identity,
        "version": AI_PROGRESS_VERSION,
        "status": "in_progress",
        "candidate_urls": [job.job_url for job in ordered_jobs],
        "evaluated_count": len(resumed_jobs),
        "total_candidates": len(ordered_jobs) + len(resumed_jobs),
    })

    def worker(listing: JobListing) -> tuple[JobListing, FitVerdict | None, bool, float]:
        state = states.get(listing.job_url) or EvaluationState(job_url=listing.job_url)
        state.start_attempt()
        state.evaluation_key = evaluation_key(listing.job_url, listing.description, profile_digest)
        store.upsert(state)
        started = time.monotonic()
        coordinator.record_candidate_start()
        if _deadline_reached(deadline):
            state.transition(DEADLINE_EXCEEDED, error="ai_deadline_exceeded", evaluation_key=state.evaluation_key)
            store.upsert(state)
            return listing, None, True, time.monotonic() - started
        verdict, unresolved = evaluate_listing(listing, deadline=deadline)
        if unresolved:
            state.transition(RETRYABLE_ERROR if not _deadline_reached(deadline) else DEADLINE_EXCEEDED, error="provider_or_deadline_failure", evaluation_key=state.evaluation_key)
        else:
            state.transition(EVALUATED, evaluation_key=state.evaluation_key, verdict=verdict.__dict__ if verdict else None)
        store.upsert(state)
        return listing, verdict, unresolved, time.monotonic() - started

    with ThreadPoolExecutor(max_workers=config.AI_MAX_CONCURRENCY, thread_name_prefix="ai-review") as executor:
        futures = {executor.submit(worker, listing): listing for listing in ordered_jobs}
        for future in as_completed(futures):
            listing = futures[future]
            try:
                listing, verdict, unresolved, duration = future.result()
            except Exception as exc:
                log.exception("AI worker crashed for '%s': %s", listing.title, exc)
                state = states.get(listing.job_url) or EvaluationState(job_url=listing.job_url)
                state.transition(RETRYABLE_ERROR, error=str(exc), evaluation_key=evaluation_key(listing.job_url, listing.description, profile_digest))
                store.upsert(state)
                verdict, unresolved, duration = None, True, 0.0

            if unresolved or verdict is None:
                coordinator.record_candidate_result(status="UNRESOLVED", duration_seconds=duration)
            else:
                passed_flag = _apply_verdict(listing, verdict)
                final_state = store.get(listing.job_url) or EvaluationState(job_url=listing.job_url)
                final_state.transition(PASSED if passed_flag else REJECTED, evaluation_key=evaluation_key(listing.job_url, listing.description, profile_digest), verdict=verdict.__dict__)
                store.upsert(final_state)
                coordinator.record_candidate_result(status="PASSED" if passed_flag else "REJECTED", duration_seconds=duration)
                if passed_flag:
                    passed.append(listing)

    deadline_reached = _deadline_reached(deadline)
    state_snapshot = store.load()
    current_by_url = {job.job_url: job for job in listings if job.job_url}
    evaluated_jobs = {}
    for url, state in state_snapshot.items():
        if state.status not in {EVALUATED, PASSED, REJECTED} or not state.verdict:
            continue
        job = current_by_url.get(url)
        if job is None:
            continue
        evaluated_jobs[url] = {
            **job.to_dict(),
            **state.verdict,
            "evaluation_key": state.evaluation_key,
            "state_status": state.status,
        }
    progress = {
        **progress_identity,
        "version": AI_PROGRESS_VERSION,
        "status": "deadline_exceeded" if deadline_reached else "completed",
        "evaluated_jobs": evaluated_jobs,
        "evaluated_count": len(evaluated_jobs),
        "total_candidates": len(ordered_jobs) + len(resumed_jobs),
        "state_store": str(store.path),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    coordinator.save_progress(progress)
    try:
        Path("run-artifacts").mkdir(parents=True, exist_ok=True)
        summary = {**coordinator.snapshot(), "candidate_count": len(ordered_jobs) + len(resumed_jobs), "status": progress["status"]}
        Path("run-artifacts/ai-metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        Path("run-artifacts/ai-evaluation-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("Could not write AI metrics artifact: %s", exc)

    retry_export = []
    for state in store.load().values():
        if state.status in {RETRYABLE_ERROR, DEADLINE_EXCEEDED, EVALUATING, QUEUED}:
            job = current_by_url.get(state.job_url)
            if job:
                retry_export.append(job)
    _save_failed_ai_jobs(retry_export)
    passed.sort(key=lambda l: l.fit_score, reverse=True)
    return passed
