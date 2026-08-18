"""Adaptive AI candidate admission control.

The controller computes a safe first-pass AI budget from the configured AI
deadline, worker concurrency, historical latency and the previous run's
unresolved rate. Admission is applied after deterministic prefiltering so the
existing broad candidate pool remains visible and deferred candidates are
explicitly recorded instead of being silently discarded.
"""
from __future__ import annotations

from pathlib import Path
import json
import math
import os
from typing import Any


PROGRESS_PATH = Path("run-artifacts/ai-progress.json")
ADMISSION_ARTIFACT = Path("run-artifacts/ai-admission.json")
DEFERRED_ARTIFACT = Path("run-artifacts/ai-admission-deferred.json")


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _load_previous_metrics() -> dict[str, Any]:
    if not PROGRESS_PATH.exists():
        return {}
    try:
        payload = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    metrics = payload.get("metrics") if isinstance(payload, dict) else None
    return metrics if isinstance(metrics, dict) else {}


def compute_admission_limit(metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    configured_max = _positive_int("MAX_LLM_CANDIDATES", 300)
    budget_seconds = _positive_float("LLM_EVALUATION_BUDGET_SECONDS", 2700)
    concurrency = _positive_int("AI_MAX_CONCURRENCY", 4)
    default_latency = _positive_float("AI_ADMISSION_DEFAULT_LATENCY_SECONDS", 90)
    safety_factor = min(
        0.95,
        max(0.35, _positive_float("AI_ADMISSION_SAFETY_FACTOR", 0.75)),
    )
    min_candidates = min(
        configured_max,
        _positive_int("AI_ADMISSION_MIN_CANDIDATES", 40),
    )

    metrics = metrics or {}
    average_latency = float(metrics.get("average_latency_seconds") or 0)
    p95_latency = float(metrics.get("p95_latency_seconds") or 0)
    estimated_latency = max(
        average_latency,
        p95_latency * 0.75,
        default_latency,
    )

    attempted = int(metrics.get("attempted") or 0)
    unresolved = int(metrics.get("unresolved") or 0)
    unresolved_ratio = (unresolved / attempted) if attempted else 0.0
    reliability_factor = max(0.50, 1.0 - min(0.50, unresolved_ratio * 0.50))
    effective_budget = budget_seconds * safety_factor * reliability_factor
    theoretical_capacity = math.floor(
        (effective_budget / estimated_latency) * concurrency
    )
    admitted = max(min_candidates, min(configured_max, theoretical_capacity))

    return {
        "configured_max_candidates": configured_max,
        "admitted_candidates": admitted,
        "budget_seconds": budget_seconds,
        "concurrency": concurrency,
        "estimated_latency_seconds": round(estimated_latency, 3),
        "safety_factor": round(safety_factor, 3),
        "reliability_factor": round(reliability_factor, 3),
        "previous_attempted": attempted,
        "previous_unresolved": unresolved,
        "previous_unresolved_ratio": round(unresolved_ratio, 4),
        "theoretical_capacity": theoretical_capacity,
    }


def apply_admission_control() -> int:
    decision = compute_admission_limit(_load_previous_metrics())
    admitted = int(decision["admitted_candidates"])

    ADMISSION_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ADMISSION_ARTIFACT.write_text(
        json.dumps(decision, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as handle:
            handle.write(f"AI_ADMISSION_LIMIT={admitted}\n")

    print(
        "AI admission control: "
        f"computed limit {admitted}/{decision['configured_max_candidates']}; "
        f"estimated_latency={decision['estimated_latency_seconds']}s; "
        f"reliability_factor={decision['reliability_factor']}"
    )
    return admitted


def admit_candidates(listings: list[Any], limit: int | None = None) -> tuple[list[Any], list[Any]]:
    """Apply the computed AI limit after deterministic prefiltering.

    The incoming list is already relevance-ranked by the existing evaluator.
    Only the strongest candidates are admitted; the remainder are explicitly
    recorded as deferred for observability and future source rediscovery.
    """
    if limit is None:
        try:
            limit = int(os.environ.get("AI_ADMISSION_LIMIT", "0"))
        except (TypeError, ValueError):
            limit = 0
    if limit <= 0:
        limit = compute_admission_limit(_load_previous_metrics())["admitted_candidates"]

    admitted = list(listings[:limit])
    deferred = list(listings[limit:])
    payload = {
        "limit": limit,
        "input_count": len(listings),
        "admitted_count": len(admitted),
        "deferred_count": len(deferred),
        "deferred_jobs": [job.to_dict() if hasattr(job, "to_dict") else job for job in deferred],
    }
    DEFERRED_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    DEFERRED_ARTIFACT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return admitted, deferred


def load_deferred_candidates() -> list[Any]:
    if not DEFERRED_ARTIFACT.exists():
        return []
    try:
        payload = json.loads(DEFERRED_ARTIFACT.read_text(encoding="utf-8"))
        jobs = payload.get("deferred_jobs", [])
        from models import JobListing
        return [JobListing(**job) for job in jobs if isinstance(job, dict)]
    except Exception:
        return []


if __name__ == "__main__":
    apply_admission_control()
