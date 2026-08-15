"""Backward-compatible migration from legacy AI progress/retry files."""
from __future__ import annotations

from typing import Any

from ai.state import EvaluationState, QUEUED, RETRYABLE_ERROR, DEADLINE_EXCEEDED, PASSED, REJECTED


def _verdict_to_status(row: dict[str, Any]) -> str:
    if row.get("fresher_appropriate") is False:
        return REJECTED
    score = row.get("fit_score")
    try:
        return PASSED if int(score) >= 0 and row.get("fresher_appropriate", True) else REJECTED
    except (TypeError, ValueError):
        return PASSED if row.get("fit_score") is not None else QUEUED


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
        state = EvaluationState(
            job_url=str(url),
            status=_verdict_to_status(row),
            attempts=max(1, int(row.get("attempts") or 1)),
            provider=row.get("provider"),
            last_error=row.get("last_error"),
            last_attempt_at=row.get("last_attempt_at"),
            evaluation_key=row.get("evaluation_key"),
            updated_at=row.get("updated_at") or payload.get("updated_at") or "",
            verdict={key: value for key, value in row.items() if key not in {"job_url", "evaluation_key", "attempts", "provider", "last_error", "last_attempt_at", "updated_at"}},
        )
        states.append(state)
    return states


def migrate_legacy_retry_jobs(jobs: list[dict[str, Any]] | None) -> list[EvaluationState]:
    """Convert failed-ai-jobs entries to RETRYABLE_ERROR states."""
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
                attempts=max(0, int(job.get("attempts") or job.get("attempt_count") or 0)),
                provider=job.get("provider"),
                last_error=job.get("last_error") or "legacy_retry_queue",
                next_retry_at=job.get("next_retry_at"),
                last_attempt_at=job.get("last_attempt_at"),
                evaluation_key=job.get("evaluation_key"),
            )
        )
    return states
