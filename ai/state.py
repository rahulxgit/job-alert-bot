"""Unified, versioned AI evaluation state model.

The state machine is the durable per-job source of truth. Legacy progress and
retry files are migration/export views only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


STATE_VERSION = 2
EVALUATION_LEASE_SECONDS = 3600

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

ALLOWED_TRANSITIONS = {
    QUEUED: {EVALUATING, DEADLINE_EXCEEDED},
    EVALUATING: {EVALUATED, RETRYABLE_ERROR, PERMANENT_ERROR, DEADLINE_EXCEEDED},
    EVALUATED: {PASSED, REJECTED, PERMANENT_ERROR},
    RETRYABLE_ERROR: {EVALUATING, DEADLINE_EXCEEDED, PERMANENT_ERROR},
    DEADLINE_EXCEEDED: {EVALUATING, PERMANENT_ERROR},
    PASSED: set(),
    REJECTED: set(),
    PERMANENT_ERROR: set(),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _is_permanent_error(error: str | None) -> bool:
    if not error:
        return False
    text = error.lower()
    permanent_markers = (
        "invalid_response", "invalid json", "invalid schema", "unsupported",
        "misconfigured", "configuration", "missing api key", "invalid api key",
        "http_400", "http_401", "http_403", "http_404", "http_422",
        "valueerror", "typeerror", "keyerror", "indexerror",
    )
    return any(marker in text for marker in permanent_markers)


@dataclass
class EvaluationState:
    job_url: str
    status: str = QUEUED
    attempts: int = 0
    provider_attempts: int = 0
    provider: str | None = None
    run_id: str | None = None
    evaluation_started_at: str | None = None
    lease_expires_at: str | None = None
    last_error: str | None = None
    next_retry_at: str | None = None
    last_attempt_at: str | None = None
    evaluation_key: str | None = None
    updated_at: str = field(default_factory=utc_now)
    verdict: dict[str, Any] | None = None

    def _sync_provider_context(self) -> None:
        """Pull per-thread provider telemetry when available, without making the
        state model depend on evaluator implementation details."""
        try:
            from ai.provider_state import get_thread_context
            context = get_thread_context()
            if context.get("provider"):
                self.provider = context["provider"]
            if context.get("provider_attempts"):
                self.provider_attempts = int(context["provider_attempts"])
        except Exception:
            return

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

        current = self.status
        target = PERMANENT_ERROR if status == RETRYABLE_ERROR and _is_permanent_error(error) else status
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if target != current and target not in allowed:
            raise ValueError(f"invalid AI state transition: {current} -> {target}")

        self._sync_provider_context()
        self.status = target
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

        if target in {EVALUATED, PASSED, REJECTED, PERMANENT_ERROR}:
            self.last_error = None if target != PERMANENT_ERROR else self.last_error
            self.next_retry_at = None
            self.lease_expires_at = None
            if target in {PASSED, REJECTED, PERMANENT_ERROR}:
                self.evaluation_started_at = None

        if target == EVALUATING:
            self.evaluation_started_at = utc_now()
            self.lease_expires_at = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + EVALUATION_LEASE_SECONDS,
                tz=timezone.utc,
            ).isoformat()
            self.run_id = self.run_id or str(uuid.uuid4())

        self.updated_at = utc_now()

    def start_attempt(self, provider: str | None = None) -> None:
        self.attempts += 1
        self.last_attempt_at = utc_now()
        self.provider = provider or self.provider
        self.provider_attempts = 0
        self.evaluation_started_at = None
        self.lease_expires_at = None
        self.last_error = None
        self.next_retry_at = None
        self.verdict = None
        self.evaluation_key = None
        # A terminal/evaluated record is historical when a new run starts.
        # Reset it to QUEUED as a new lifecycle, then enter EVALUATING through
        # the normal validated transition path.
        if self.status in {EVALUATED, PASSED, REJECTED, PERMANENT_ERROR}:
            self.status = QUEUED
        self.run_id = str(uuid.uuid4())
        self.transition(EVALUATING, provider=provider)

    def is_stale(self, now: datetime | None = None) -> bool:
        if self.status != EVALUATING:
            return False
        if not self.lease_expires_at:
            return True
        try:
            expiry = datetime.fromisoformat(self.lease_expires_at)
        except (TypeError, ValueError):
            return True
        current = now or datetime.now(timezone.utc)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return current >= expiry

    def mark_stale(self) -> None:
        if self.status != EVALUATING:
            return
        self.status = RETRYABLE_ERROR
        self.last_error = "stale_evaluation_lease"
        self.lease_expires_at = None
        self.evaluation_started_at = None
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["version"] = STATE_VERSION
        return data


def from_dict(data: dict[str, Any]) -> EvaluationState | None:
    if not isinstance(data, dict):
        return None
    raw_version = _safe_int(data.get("version"), 0)
    if raw_version not in {1, STATE_VERSION}:
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
        provider_attempts=_safe_int(data.get("provider_attempts")),
        provider=str(data.get("provider") or "") or None,
        run_id=str(data.get("run_id") or "") or None,
        evaluation_started_at=data.get("evaluation_started_at"),
        lease_expires_at=data.get("lease_expires_at"),
        last_error=data.get("last_error") or data.get("error"),
        next_retry_at=data.get("next_retry_at"),
        last_attempt_at=data.get("last_attempt_at"),
        evaluation_key=data.get("evaluation_key"),
        updated_at=data.get("updated_at") or utc_now(),
        verdict=data.get("verdict") if isinstance(data.get("verdict"), dict) else None,
    )
