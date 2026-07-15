"""
Real scheduling is handled externally by GitHub Actions'
.github/workflows/job-alerts.yml cron trigger (8 AM IST daily) — this
module is NOT used in the GitHub Actions run. It exists only to support
running the bot locally on a loop if that's ever wanted outside Actions.

Usage: python scheduler.py --interval-hours 24
"""
import argparse
import time
from main import run_pipeline
from utils.logging_setup import get_logger

log = get_logger("scheduler")


def run_forever(interval_hours: float):
    while True:
        log.info("Running pipeline...")
        try:
            run_pipeline()
        except Exception as exc:
            log.warning(f"Pipeline run failed: {exc}")
        log.info(f"Sleeping {interval_hours}h until next run.")
        time.sleep(interval_hours * 3600)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-hours", type=float, default=24.0)
    args = parser.parse_args()
    run_forever(args.interval_hours)
