"""Company career pages via Lever's public API — same reliability profile
as Greenhouse. Only covers companies configured in config.LEVER_BOARDS."""
import os
import time
import requests

import config
from models import JobListing
from sources.base import JobSource
from utils.logging_setup import get_logger

log = get_logger("lever")


class LeverSource(JobSource):
    name = "Lever"

    def fetch_listings(self) -> list[JobListing]:
        rows = []
        breaker_threshold = max(1, int(os.environ.get("SOURCE_404_BREAKER_THRESHOLD", "3")))
        consecutive_404s = 0

        for company_name, token in config.LEVER_BOARDS.items():
            if consecutive_404s >= breaker_threshold:
                log.warning(
                    "Lever circuit breaker opened after %s consecutive 404s; "
                    "skipping remaining boards for this run",
                    consecutive_404s,
                )
                break
            try:
                resp = requests.get(
                    f"https://api.lever.co/v0/postings/{token}",
                    params={"mode": "json"},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                consecutive_404s = 0
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 404:
                    consecutive_404s += 1
                    log.warning(
                        "fetch failed for '%s' (token '%s'): 404 Not Found, consecutive=%s/%s",
                        company_name, token, consecutive_404s, breaker_threshold,
                    )
                else:
                    consecutive_404s = 0
                    log.warning("fetch failed for '%s' (token '%s'): %s", company_name, token, exc)
                continue
            except Exception as exc:
                consecutive_404s = 0
                log.warning("fetch failed for '%s' (token '%s'): %s", company_name, token, exc)
                continue

            for job in data:
                categories = job.get("categories", {})
                rows.append(JobListing(
                    job_url=job.get("hostedUrl", ""), title=job.get("text", ""), company=company_name,
                    location=categories.get("location", "India") if isinstance(categories, dict) else "India",
                    description=job.get("descriptionPlain", "") or job.get("text", ""), source=self.name,
                ))
            time.sleep(1)
        return rows
