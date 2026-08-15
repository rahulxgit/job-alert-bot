"""Thread-safe AI evaluation metrics and serialized checkpoint writes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
import json
import os


@dataclass
class AIMetrics:
    attempted: int = 0
    completed: int = 0
    unresolved: int = 0
    passed: int = 0
    rejected: int = 0
    retry_attempts: int = 0
    latency_seconds: list[float] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        latencies = sorted(self.latency_seconds)
        avg = sum(latencies) / len(latencies) if latencies else 0.0
        if latencies:
            index = max(0, min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1)))))
            p95 = latencies[index]
        else:
            p95 = 0.0
        return {
            "attempted": self.attempted,
            "completed": self.completed,
            "unresolved": self.unresolved,
            "passed": self.passed,
            "rejected": self.rejected,
            "retry_attempts": self.retry_attempts,
            "average_latency_seconds": round(avg, 3),
            "p95_latency_seconds": round(p95, 3),
        }


class MetricsCoordinator:
    """Owns all mutable AI metrics and serializes checkpoint writes."""

    def __init__(self, progress_path: Path, metrics_enabled: bool = True) -> None:
        self.progress_path = progress_path
        self.metrics_enabled = metrics_enabled
        self.metrics = AIMetrics()
        self._lock = Lock()

    def record_candidate_start(self) -> None:
        if not self.metrics_enabled:
            return
        with self._lock:
            self.metrics.attempted += 1

    def record_retry(self) -> None:
        if not self.metrics_enabled:
            return
        with self._lock:
            self.metrics.retry_attempts += 1

    def record_candidate_result(self, *, status: str, duration_seconds: float) -> None:
        """Record exactly one terminal candidate state.

        status is one of PASSED, REJECTED, or UNRESOLVED. This single API keeps
        evaluator and metrics state aligned and prevents double-counting.
        """
        if status not in {"PASSED", "REJECTED", "UNRESOLVED"}:
            raise ValueError(f"invalid AI candidate status: {status}")
        if not self.metrics_enabled:
            return
        with self._lock:
            self.metrics.latency_seconds.append(max(0.0, duration_seconds))
            if status == "UNRESOLVED":
                self.metrics.unresolved += 1
            else:
                self.metrics.completed += 1
                if status == "PASSED":
                    self.metrics.passed += 1
                else:
                    self.metrics.rejected += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.metrics.snapshot() if self.metrics_enabled else {}

    @staticmethod
    def _legacy_evaluated_jobs(progress_path: Path) -> dict[str, Any]:
        """Build the legacy evaluated_jobs export from authoritative ai-state.json."""
        state_path = progress_path.with_name("ai-state.json")
        if not state_path.exists():
            return {}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}
        raw_states = payload.get("states", {}) if isinstance(payload, dict) else {}
        if not isinstance(raw_states, dict):
            return {}

        evaluated: dict[str, Any] = {}
        terminal_states = {"EVALUATED", "PASSED", "REJECTED"}
        for url, state in raw_states.items():
            if not isinstance(state, dict) or state.get("status") not in terminal_states:
                continue
            verdict = state.get("verdict")
            record: dict[str, Any] = {
                "job_url": url,
                "evaluation_key": state.get("evaluation_key"),
                "attempts": state.get("attempts", 0),
                "provider": state.get("provider"),
                "last_attempt_at": state.get("last_attempt_at"),
                "updated_at": state.get("updated_at"),
            }
            if isinstance(verdict, dict):
                record.update(verdict)
            evaluated[url] = record
        return evaluated

    def save_progress(self, progress: dict[str, Any]) -> None:
        """Atomically write progress and a compatibility export derived from ai-state.json."""
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            progress["evaluated_jobs"] = self._legacy_evaluated_jobs(self.progress_path)
            progress["metrics"] = self.metrics.snapshot() if self.metrics_enabled else {}
            progress["updated_at"] = datetime.now(timezone.utc).isoformat()
            tmp_path = self.progress_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp_path, self.progress_path)
