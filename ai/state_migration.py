"""Backward-compatible migration from legacy AI progress/retry files."""
from __future__ import annotations

from typing import Any

from ai.state import (
    EvaluationState,
    PASSED,
    REJECTED,
    RETRYABLE_ERROR,
    DEADLINE_EXCEEDED,
    EVALUATED,
    PERMANENT_ERROR,
    _safe_int,
)


def _verdict_to_status(row: dict[str, Any]) -> str:
    if row.get("fresher_appropriate") is False:
        return REJECTED
    decision = str(row.get("decision") or "").strip().lower()
    if decision == "reject":
        return REJECTED
    if decision in {"strong_match", "good_match"}:
        return PASSED if row.get("fresher_appropriate") is True else REJECTED
    if decision == "weak_match":
        return EVALUATED
    score = _safe_int(row.get("fit_score"), 0)
    return PASSED if score >= 70 and row.get("fresher_appropriate") is True else REJECTED


def migrate_legacy_progress(payload: dict[str, Any] | None) -> list[EvaluationState]:
    """Convert completed checkpoint entries into unified evaluation states."""
    if not isinstance(payload, dict):
        return []
    rows = payload.get("evaluated_jobs", {})
    if not isinstance(rows, dict):
        return []
    states: list[EvaluationState] = []
    for url, row in rows.items():
        if not isinstance(row, dict) or not str(url).strip():
            continue
        states.append(
            EvaluationState(
                job_url=str(url),
                status=_verdict_to_status(row),
                attempts=max(1, _safe_int(row.get("attempts"), 1)),
                provider=row.get("provider"),
                provider_attempts=_safe_int(row.get("provider_attempts"), 0),
                last_error=row.get("last_error"),
                last_attempt_at=row.get("last_attempt_at"),
                evaluation_key=row.get("evaluation_key"),
                updated_at=row.get("updated_at") or payload.get("updated_at") or "",
                verdict={
                    key: value
                    for key, value in row.items()
                    if key not in {
                        "job_url", "evaluation_key", "attempts", "provider",
                        "provider_attempts", "last_error", "last_attempt_at", "updated_at",
                    }
                },
            )
        )
    return states


def migrate_legacy_retry_jobs(jobs: list[dict[str, Any]] | None) -> list[EvaluationState]:
    """Convert failed-ai-jobs entries to RETRYABLE_ERROR states safely."""
    if not isinstance(jobs, list):
        return []
    states: list[EvaluationState] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        url = str(job.get("job_url") or "").strip()
        if not url:
            continue
        states.append(
            EvaluationState(
                job_url=url,
                status=RETRYABLE_ERROR,
                attempts=_safe_int(job.get("attempts"), _safe_int(job.get("attempt_count"), 0)),
                provider=job.get("provider"),
                provider_attempts=_safe_int(job.get("provider_attempts"), 0),
                last_error=job.get("last_error") or "legacy_retry_queue",
                next_retry_at=job.get("next_retry_at"),
                last_attempt_at=job.get("last_attempt_at"),
                evaluation_key=job.get("evaluation_key"),
            )
        )
    return states


MIGRATION_PRECEDENCE = {
    PASSED: 100,
    REJECTED: 100,
    PERMANENT_ERROR: 95,
    EVALUATED: 90,
    DEADLINE_EXCEEDED: 50,
    RETRYABLE_ERROR: 40,
}


def resolve_migration_conflicts(states: list[EvaluationState]) -> list[EvaluationState]:
    """Keep the strongest state when the legacy files disagree on one URL."""
    by_url: dict[str, EvaluationState] = {}
    for state in states:
        current = by_url.get(state.job_url)
        if current is None:
            by_url[state.job_url] = state
            continue
        current_rank = MIGRATION_PRECEDENCE.get(current.status, 0)
        candidate_rank = MIGRATION_PRECEDENCE.get(state.status, 0)
        if candidate_rank > current_rank:
            by_url[state.job_url] = state
        elif candidate_rank == current_rank:
            # Prefer the newer record when legacy timestamps are available.
            if (state.updated_at or "") > (current.updated_at or ""):
                by_url[state.job_url] = state
    return list(by_url.values())
