"""Export sanitized pipeline snapshots for GitHub Actions recovery/debugging."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ARTIFACT_DIR = Path(os.environ.get("JOB_RUN_ARTIFACT_DIR", "run-artifacts"))


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _job_rows(listings: Iterable[Any]) -> list[dict[str, Any]]:
    rows = []
    for listing in listings:
        if hasattr(listing, "to_dict"):
            row = listing.to_dict()
        else:
            row = _jsonable(listing)
        rows.append(_jsonable(row))
    return rows


def export_stage(stage: str, listings: Iterable[Any], *, metadata: dict[str, Any] | None = None) -> str:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _job_rows(listings)
    payload = {
        "stage": stage,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "metadata": metadata or {},
        "jobs": rows,
    }
    path = ARTIFACT_DIR / f"{stage}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def export_summary(summary: dict[str, Any]) -> str:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / "run-summary.json"
    payload = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        **summary,
    }
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
