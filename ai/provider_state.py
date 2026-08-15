"""Provider lifecycle state and telemetry for concurrent AI evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, local
from typing import Any
import json
import os
import time


PROVIDER_STATES = {
    "AVAILABLE",
    "DEGRADED",
    "RATE_LIMITED",
    "TIMEOUTING",
    "CIRCUIT_OPEN",
    "RECOVERING",
}

_PROVIDER_ARTIFACT = Path("run-artifacts/ai-provider-state.json")
_thread_context = local()


@dataclass
class _ProviderRecord:
    state: str = "AVAILABLE"
    consecutive_failures: int = 0
    requests: int = 0
    successes: int = 0
    timeouts: int = 0
    rate_limits: int = 0
    server_errors: int = 0
    invalid_responses: int = 0
    other_errors: int = 0
    recovery_count: int = 0
    total_latency_seconds: float = 0.0
    last_error: str | None = None
    last_transition_at: str = ""
    cooldown_until: float = 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "requests": self.requests,
            "successes": self.successes,
            "timeouts": self.timeouts,
            "rate_limits": self.rate_limits,
            "server_errors": self.server_errors,
            "invalid_responses": self.invalid_responses,
            "other_errors": self.other_errors,
            "recovery_count": self.recovery_count,
            "average_latency_seconds": round(self.total_latency_seconds / self.requests, 3) if self.requests else 0.0,
            "last_error": self.last_error,
            "last_transition_at": self.last_transition_at,
            "cooldown_active": self.cooldown_until > time.monotonic(),
        }


_records: dict[str, _ProviderRecord] = {}
_lock = Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_for(provider: str) -> _ProviderRecord:
    return _records.setdefault(provider, _ProviderRecord(last_transition_at=_utc_now()))


def _context() -> dict[str, Any]:
    ctx = getattr(_thread_context, "value", None)
    if ctx is None:
        ctx = {"provider": None, "provider_attempts": 0, "last_failure": None}
        _thread_context.value = ctx
    return ctx


def reset_thread_context() -> None:
    _thread_context.value = {"provider": None, "provider_attempts": 0, "last_failure": None}


def get_thread_context() -> dict[str, Any]:
    return dict(_context())


def _persist_locked() -> None:
    _PROVIDER_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _utc_now(),
        "providers": {name: record.snapshot() for name, record in _records.items()},
    }
    tmp = _PROVIDER_ARTIFACT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _PROVIDER_ARTIFACT)


def record_request(provider: str) -> None:
    ctx = _context()
    ctx["provider"] = provider
    ctx["provider_attempts"] += 1
    ctx["last_failure"] = None
    with _lock:
        _record_for(provider).requests += 1
        _persist_locked()


def record_success(provider: str, latency_seconds: float) -> None:
    ctx = _context()
    ctx["provider"] = provider
    ctx["last_failure"] = None
    with _lock:
        record = _record_for(provider)
        previous_state = record.state
        record.successes += 1
        record.consecutive_failures = 0
        record.total_latency_seconds += max(0.0, latency_seconds)
        record.last_error = None
        record.state = "AVAILABLE" if previous_state != "AVAILABLE" else previous_state
        if previous_state in {"DEGRADED", "RATE_LIMITED", "TIMEOUTING", "CIRCUIT_OPEN"}:
            record.recovery_count += 1
            record.state = "RECOVERING"
        record.last_transition_at = _utc_now()
        if record.state == "RECOVERING":
            record.state = "AVAILABLE"
        _persist_locked()


def record_failure(provider: str, kind: str, latency_seconds: float = 0.0, cooldown_seconds: float = 0.0) -> None:
    normalized = kind.upper()
    ctx = _context()
    ctx["provider"] = provider
    ctx["last_failure"] = normalized
    with _lock:
        record = _record_for(provider)
        record.consecutive_failures += 1
        record.total_latency_seconds += max(0.0, latency_seconds)
        record.last_error = normalized
        if normalized in {"TIMEOUT", "TIMEOUTING"}:
            record.timeouts += 1
            record.state = "TIMEOUTING"
        elif normalized in {"RATE_LIMIT", "RATE_LIMITED", "HTTP_429"}:
            record.rate_limits += 1
            record.state = "RATE_LIMITED"
        elif normalized in {"HTTP_5XX", "SERVER_ERROR"}:
            record.server_errors += 1
            record.state = "DEGRADED"
        elif normalized in {"INVALID_JSON", "INVALID_RESPONSE", "INVALID_SCHEMA"}:
            record.invalid_responses += 1
            record.state = "DEGRADED"
        else:
            record.other_errors += 1
            record.state = "DEGRADED"

        if cooldown_seconds > 0:
            record.cooldown_until = max(record.cooldown_until, time.monotonic() + cooldown_seconds)
        if record.consecutive_failures >= 3:
            record.state = "CIRCUIT_OPEN"
        record.last_transition_at = _utc_now()
        _persist_locked()


def snapshot() -> dict[str, Any]:
    with _lock:
        return {name: record.snapshot() for name, record in _records.items()}


def reset_for_tests() -> None:
    reset_thread_context()
    with _lock:
        _records.clear()
        if _PROVIDER_ARTIFACT.exists():
            _PROVIDER_ARTIFACT.unlink()
