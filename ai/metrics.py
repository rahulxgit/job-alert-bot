"""Thread-safe AI evaluation metrics and checkpoint coordination primitives."""
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
    """Owns mutable metrics and serializes checkpoint writes."""

    def __init__(self, progress_path: Path, metrics_enabled: bool = True) -> None:
        self.progress_path = progress_path
        self.metrics_enabled = metrics_enabled
        self.metrics = AIMetrics()
        self._lock = Lock()
        self._pending_result: bool | None = None

    def record_candidate_start(self) -> None:
        if not self.metrics_enabled:
            return
        with self._lock:
            self.metrics.attempted += 1

    def record_worker_result(self, *, passed: bool | None, duration_seconds: float) -> None:
        if not self.metrics_enabled:
            return
        with self._lock:
            self.metrics.latency_seconds.append(max(0.0, duration_seconds))
            if passed is None:
                self.metrics.unresolved += 1
            else:
                self.metrics.completed += 1
                if passed:
                    self.metrics.passed += 1
                else:
                    self.metrics.rejected += 1

    def record_result(self, passed: bool | None) -> None:
        """Backward-compatible result API used by the evaluator coordinator.

        The evaluator records ``False`` before applying the verdict and, when
        the verdict passes, immediately records ``True``. We defer a False
        result until the next result so the final counters stay accurate.
        """
        if not self.metrics_enabled:
            return
        with self._lock:
            if passed is None:
                if self._pending_result is False:
                    self.metrics.completed += 1
                    self.metrics.rejected += 1
                self._pending_result = None
                self.metrics.unresolved += 1
                return

            if passed:
                if self._pending_result is False:
                    self._pending_result = None
                self.metrics.completed += 1
                self.metrics.passed += 1
                return

            if self._pending_result is False:
                self.metrics.completed += 1
                self.metrics.rejected += 1
            self._pending_result = False

    def record_retry(self) -> None:
        if not self.metrics_enabled:
            return
        with self._lock:
            self.metrics.retry_attempts += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self.metrics.snapshot()
            if self.metrics_enabled and self._pending_result is False:
                snapshot["completed"] += 1
                snapshot["rejected"] += 1
            return snapshot

    def save_progress(self, progress: dict[str, Any]) -> None:
        """Atomically write progress from the coordinator thread only."""
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            progress["metrics"] = self.metrics.snapshot() if self.metrics_enabled else {}
            if self.metrics_enabled and self._pending_result is False:
                progress["metrics"]["completed"] += 1
                progress["metrics"]["rejected"] += 1
            progress["updated_at"] = datetime.now(timezone.utc).isoformat()
            tmp_path = self.progress_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp_path, self.progress_path)
