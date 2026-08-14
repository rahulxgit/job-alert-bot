"""Source-level health and coverage metrics for the job collection pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


ERROR_CLASSIFICATIONS = {
    "TIMEOUT",
    "NETWORK_ERROR",
    "HTTP_403",
    "HTTP_429",
    "HTTP_5XX",
    "AUTH_ERROR",
    "PARSER_ERROR",
    "BLOCKED",
    "NO_RESULTS",
    "DISABLED",
    "UNKNOWN_ERROR",
}


@dataclass
class SourceHealth:
    name: str
    status: str = "HEALTHY"
    jobs_found: int = 0
    duration_seconds: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    errors: list[str] = field(default_factory=list)
    error_classification: str | None = None
    retries: int = 0
    http_api_failures: int = 0
    duplicate_jobs: int = 0
    urls_discovered: int = 0
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_exception(exc: Exception) -> str:
    text = str(exc).lower()
    name = type(exc).__name__.lower()

    if "timeout" in text or "timeout" in name:
        return "TIMEOUT"
    if "403" in text or "forbidden" in text:
        return "HTTP_403"
    if "429" in text or "too many requests" in text or "rate limit" in text:
        return "HTTP_429"
    if any(token in text for token in ("401", "unauthorized", "authentication", "api key")):
        return "AUTH_ERROR"
    if any(token in text for token in ("500", "502", "503", "504", "server error")):
        return "HTTP_5XX"
    if any(token in name for token in ("connection", "request", "network")):
        return "NETWORK_ERROR"
    if any(token in text for token in ("blocked", "captcha", "bot detection", "robot")):
        return "BLOCKED"
    if any(token in text for token in ("json", "parse", "parser", "schema")):
        return "PARSER_ERROR"
    return "UNKNOWN_ERROR"


def finalize_health(health: SourceHealth, listings_count: int) -> SourceHealth:
    health.jobs_found = listings_count
    health.urls_discovered = listings_count
    health.finished_at = utc_now()
    if not health.started_at:
        health.started_at = health.finished_at
    start = datetime.fromisoformat(health.started_at)
    finish = datetime.fromisoformat(health.finished_at)
    health.duration_seconds = max(0.0, (finish - start).total_seconds())

    if not health.enabled:
        health.status = "DISABLED"
    elif health.errors:
        health.status = "FAILED" if listings_count == 0 else "DEGRADED"
    elif listings_count == 0:
        health.status = "HEALTHY"
        health.error_classification = "NO_RESULTS"
    else:
        health.status = "HEALTHY"
    return health


def build_search_summary(
    *,
    source_health: dict[str, SourceHealth],
    raw_listings: int,
    unique_listings: int,
    source_breakdown: dict[str, int],
    duplicate_count: int,
    duration_seconds: float,
    status: str,
) -> dict[str, Any]:
    health_values = list(source_health.values())
    enabled = [item for item in health_values if item.enabled]
    return {
        "status": status,
        "total_raw_jobs": raw_listings,
        "total_unique_jobs": unique_listings,
        "duplicate_count": duplicate_count,
        "sources_enabled": len(enabled),
        "sources_healthy": sum(item.status == "HEALTHY" for item in enabled),
        "sources_degraded": sum(item.status == "DEGRADED" for item in enabled),
        "sources_failed": sum(item.status == "FAILED" for item in enabled),
        "sources_zero_results": sum(item.jobs_found == 0 for item in enabled),
        "source_breakdown": source_breakdown,
        "source_percentage": {
            name: round(count / unique_listings * 100, 2) if unique_listings else 0.0
            for name, count in source_breakdown.items()
        },
        "duration_seconds": round(duration_seconds, 3),
        "sources": {name: item.to_dict() for name, item in source_health.items()},
    }
