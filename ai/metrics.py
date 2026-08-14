"""Thread-safe AI evaluation metrics and checkpoint coordination primitives."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
import json
import os
import time


@dataclass
class AIMetrics:
    attempted: int = 0
    completed: int = 0
    unresolved: int = 0
    passed: int = 0
    rejected: int = 0
    gateway_success: int = 0
    gateway_failure: int = 0
    gemini_success: int = 0
    gemini_rate_limited: int = 0
    provider_failures: int = 0
    retry_attempts: int = 0
    latency_seconds: list[float] = field(default_factory=list)
    provider_latency_seconds: Counter = field(default_factory=Counter)

    def record_attempt(self) -> None:
        self.attempted += 1

    def record_completion(self, passed: bool) -> None:
        self.completed += 1
        if passed:
            self.passed += 1
        else:
            self.rejected += 1

    def record_unresolved(self) -> None:
        self.unresolved += 1
        self.provider_failures += 1

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
            "gateway_success": self.gateway_success,
            "gateway_failure": self.gateway_failure,
            "gemini_success": self.gemini_success,
            "gemini_rate_limited": self.gemini_rate_limited,
            "provider_failures": self.provider_failures,
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

    def record_candidate_start(self) -> None:
        if not self.metrics_enabled:
            return
        with self._lock:
            self.metrics.record_attempt()

    def record_provider_event(self, provider: str, success: bool, latency_seconds: float, *, rate_limited: bool = False) -> None:
        if not self.metrics_enabled:
            return
        with self._lock:
            self.metrics.latency_seconds.append(max(0.0, latency_seconds))
            self.metrics.provider_latency_seconds[provider] += max(0.0, latency_seconds)
            if provider == "gateway":
                if success:
                    self.metrics.gateway_success += 1
                else:
                    self.metrics.gateway_failure += 1
            elif provider == "gemini":
                if success:
                    self.metrics.gemini_success += 1
                if rate_limited:
                    self.metrics.gemini_rate_limited += 1

    def record_retry(self) -> None:
        if not self.metrics_enabled:
            return
        with self._lock:
            self.metrics.retry_attempts += 1

    def record_result(self, *, passed: bool | None) -> None:
        if not self.metrics_enabled:
            return
        with self._lock:
            if passed is None:
                self.metrics.record_unresolved()
            else:
                self.metrics.record_completion(passed)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.metrics.snapshot()

    def save_progress(self, progress: dict[str, Any]) -> None:
        """Atomically write progress from the coordinator thread only."""
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            progress["metrics"] = self.metrics.snapshot() if self.metrics_enabled else {}
            progress["updated_at"] = datetime.now(timezone.utc).isoformat()
            tmp_path = self.progress_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp_path, self.progress_path)
