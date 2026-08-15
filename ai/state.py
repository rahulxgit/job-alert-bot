"""Unified, versioned AI evaluation state model.

One logical record owns the lifecycle of each candidate. Legacy checkpoint and
retry representations can be normalized into this model without changing the
meaning of a completed evaluation or a retryable failure.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


STATE_VERSION = 1

QUEUED = "QUEUED"
EVALUATING = "EVALUATING"
EVALUATED = "EVALUATED"
PASSED = "PASSED"
REJECTED = "REJECTED"
RETRYABLE_ERROR = "RETRYABLE_ERROR"
PERMANENT_ERROR = "PERMANENT_ERROR"
DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"

ALL_STATES = {
    QUEUED, EVALUATING, EVALUATED, PASSED, REJECTED,
    RETRYABLE_ERROR, PERMANENT_ERROR, DEADLINE_EXCEEDED,
}
TERMINAL_STATES = {PASSED, REJECTED, PERMANENT_ERROR}
RESUMABLE_STATES = {QUEUED, RETRYABLE_ERROR, DEADLINE_EXCEEDED, EVALUATING}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EvaluationState:
    job_url: str
    status: str = QUEUED
    attempts: int = 0
    provider: str | None = None
    last_error: str | None = None
    next_retry_at: str | None = None
    last_attempt_at: str | None = None
    evaluation_key: str | None = None
    updated_at: str = field(default_factory=utc_now)
    verdict: dict[str, Any] | None = None

    def transition(
        self,
        status: str,
        *,
        provider: str | None = None,
        error: str | None = None,
        next_retry_at: str | None = None,
        evaluation_key: str | None = None,
        verdict: dict[str, Any] | None = None,
    ) -> None:
        if status not in ALL_STATES:
            raise ValueError(f"unknown AI state: {status}")
        self.status = status
        if provider is not None:
            self.provider = provider
        if error is not None:
            self.last_error = error
        if next_retry_at is not None:
            self.next_retry_at = next_retry_at
        if evaluation_key is not None:
            self.evaluation_key = evaluation_key
        if verdict is not None:
            self.verdict = verdict
        self.updated_at = utc_now()

    def start_attempt(self, provider: str | None = None) -> None:
        self.attempts += 1
        self.last_attempt_at = utc_now()
        if provider is not None:
            self.provider = provider
        self.status = EVALUATING
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["version"] = STATE_VERSION
        return data


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def from_dict(data: dict[str, Any]) -> EvaluationState | None:
    if not isinstance(data, dict):
        return None
    job_url = str(data.get("job_url") or "").strip()
    if not job_url:
        return None
    raw_status = str(data.get("status") or QUEUED).upper()
    status = {
        "FAILED": RETRYABLE_ERROR,
        "UNRESOLVED": RETRYABLE_ERROR,
        "RETRY": RETRYABLE_ERROR,
        "RETRYABLE": RETRYABLE_ERROR,
        "DEADLINE": DEADLINE_EXCEEDED,
    }.get(raw_status, raw_status)
    if status not in ALL_STATES:
        return None
    return EvaluationState(
        job_url=job_url,
        status=status,
        attempts=_safe_int(data.get("attempts"), _safe_int(data.get("attempt_count"))),
        provider=str(data.get("provider") or "") or None,
        last_error=data.get("last_error") or data.get("error"),
        next_retry_at=data.get("next_retry_at"),
        last_attempt_at=data.get("last_attempt_at"),
        evaluation_key=data.get("evaluation_key"),
        updated_at=data.get("updated_at") or utc_now(),
        verdict=data.get("verdict") if isinstance(data.get("verdict"), dict) else None,
    )
