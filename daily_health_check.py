"""Daily health check for job-alert-bot.

Runs the same review I do manually each morning: git hygiene, gitignore
integrity, latest run log for errors/gateway flakiness, and whether the
local run-artifacts are actually from today's run or stale leftovers.

Usage:
    python daily_health_check.py            # normal run, prints summary
    python daily_health_check.py --verbose  # also show clean/passing checks

Exit code is non-zero if anything needs attention, so this can be wired
into a scheduled task or a pre-standup script without extra parsing.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
ISSUES: list[str] = []
NOTES: list[str] = []

ERROR_PATTERNS = (
    "ERROR",
    "Traceback",
    "gateway unavailable",
    "rate limited",
    "deadline_exceeded",
    "Cloudflare JS challenge",
)


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def check_git_status() -> None:
    status = run_git("status", "--porcelain")
    if not status:
        NOTES.append("git status clean.")
        return
    dirty_lines = status.splitlines()
    ISSUES.append(
        f"git status is not clean ({len(dirty_lines)} entries):\n"
        + "\n".join(f"    {line}" for line in dirty_lines)
    )


def check_gitignore_integrity() -> None:
    gitignore_path = REPO_ROOT / ".gitignore"
    if not gitignore_path.exists():
        ISSUES.append(".gitignore is missing entirely.")
        return

    raw = gitignore_path.read_bytes()
    if b"\x00" in raw:
        ISSUES.append(
            ".gitignore contains null bytes — likely a UTF-16 encoding leak "
            "(this exact bug bit us once already, on the run-artifacts/ line)."
        )
        return

    must_ignore = ["run-artifacts/dummy.json", "temp_artifacts/dummy.json", "dummy.log"]
    for target in must_ignore:
        result = subprocess.run(
            ["git", "check-ignore", target],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            ISSUES.append(f".gitignore is not actually excluding '{target}' pattern group.")
    if not any("gitignore" in issue for issue in ISSUES):
        NOTES.append(".gitignore encoding and rules look correct.")


def find_latest_run_log() -> Path | None:
    candidates = list(REPO_ROOT.glob("run_*.log")) + list(REPO_ROOT.glob("run-*.log"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def check_latest_run_log() -> None:
    log_path = find_latest_run_log()
    if log_path is None:
        NOTES.append("No run_*.log found locally — nothing to scan.")
        return

    raw = log_path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        encoding = "utf-16"
    else:
        encoding = "utf-8"
    text = raw.decode(encoding, errors="ignore")

    hits: dict[str, int] = {}
    for line in text.splitlines():
        for pattern in ERROR_PATTERNS:
            if pattern.lower() in line.lower():
                hits[pattern] = hits.get(pattern, 0) + 1

    if not hits:
        NOTES.append(f"{log_path.name}: no error/warning patterns found.")
        return

    summary = ", ".join(f"{pattern}={count}" for pattern, count in hits.items())
    ISSUES.append(f"{log_path.name} has warning/error patterns: {summary}")


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def check_artifact_freshness() -> None:
    progress_path = REPO_ROOT / "run-artifacts" / "ai-progress.json"
    metrics_path = REPO_ROOT / "run-artifacts" / "ai-metrics.json"

    if not progress_path.exists() or not metrics_path.exists():
        NOTES.append("run-artifacts/ai-progress.json or ai-metrics.json not present locally.")
        return

    progress = load_json(progress_path)
    if progress is None:
        ISSUES.append("ai-progress.json exists but failed to parse as JSON.")
        return

    progress_mtime = datetime.fromtimestamp(progress_path.stat().st_mtime, tz=timezone.utc)
    metrics_mtime = datetime.fromtimestamp(metrics_path.stat().st_mtime, tz=timezone.utc)
    drift_seconds = abs((progress_mtime - metrics_mtime).total_seconds())

    if drift_seconds > 300:
        ISSUES.append(
            f"ai-metrics.json and ai-progress.json are {drift_seconds / 60:.1f} minutes "
            "apart — one of them is probably stale leftover data, not from the same run."
        )
    else:
        NOTES.append("run-artifacts timestamps are consistent with each other.")

    status = progress.get("status")
    if status and status != "completed":
        ISSUES.append(f"Last local AI evaluation checkpoint status is '{status}', not 'completed'.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="show passing checks too")
    args = parser.parse_args()

    checks = (
        check_git_status,
        check_gitignore_integrity,
        check_latest_run_log,
        check_artifact_freshness,
    )
    for check in checks:
        check()

    print(f"job-alert-bot daily health check — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    if args.verbose and NOTES:
        print("OK:")
        for note in NOTES:
            print(f"  - {note}")
        print()

    if ISSUES:
        print("NEEDS ATTENTION:")
        for issue in ISSUES:
            print(f"  - {issue}")
        return 1

    print("Nothing needs attention today.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
