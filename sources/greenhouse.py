"""Company career pages via Greenhouse's public API — genuinely reliable,
unlike Wellfound/Naukri, since this is a real documented public endpoint.
Only covers companies configured in config.GREENHOUSE_BOARDS."""
import os
import time
import requests

import config
from models import JobListing
from sources.base import JobSource
from utils.logging_setup import get_logger

log = get_logger("greenhouse")


class GreenhouseSource(JobSource):
    name = "Greenhouse"

    def fetch_listings(self) -> list[JobListing]:
        rows = []
        breaker_threshold = max(1, int(os.environ.get("SOURCE_404_BREAKER_THRESHOLD", "3")))
        consecutive_404s = 0

        for company_name, token in config.GREENHOUSE_BOARDS.items():
            if consecutive_404s >= breaker_threshold:
                log.warning(
                    "Greenhouse circuit breaker opened after %s consecutive 404s; "
                    "skipping remaining boards for this run",
                    consecutive_404s,
                )
                break
            data = None
            for attempt in range(3):
                try:
                    resp = requests.get(
                        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                        params={"content": "true"}, timeout=15,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    consecutive_404s = 0
                    break
                except requests.exceptions.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else None
                    if status == 404:
                        consecutive_404s += 1
                        log.warning(
                            "fetch failed for '%s' (token '%s'): 404 Not Found, consecutive=%s/%s",
                            company_name, token, consecutive_404s, breaker_threshold,
                        )
                        break
                    elif status in (429, 500, 502, 503, 504) and attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                    else:
                        consecutive_404s = 0
                        log.warning("fetch failed for '%s' (token '%s'): %s", company_name, token, exc)
                        break
                except Exception as exc:
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                    consecutive_404s = 0
                    log.warning("fetch failed for '%s' (token '%s'): %s", company_name, token, exc)
                    break
            
            if not data:
                continue

            for job in data.get("jobs", []):
                location = job.get("location", {})
                rows.append(JobListing(
                    job_url=job.get("absolute_url", ""), title=job.get("title", ""),
                    company=company_name,
                    location=location.get("name", "India") if isinstance(location, dict) else "India",
                    description=job.get("content", "") or job.get("title", ""), source=self.name,
                ))
            time.sleep(1)
        return rows
