"""Naukri — via their internal search API (naukri.com/jobapi/v3/search).
Not officially documented or supported; the most fragile source in this
project. Naukri can change required headers, rate-limit harder, or
restructure the response at any time. If this consistently returns 0,
that's most likely the culprit, not a bug elsewhere."""
import os
import time
import requests

import config
from models import JobListing
from sources.base import JobSource
from utils.logging_setup import get_logger

log = get_logger("naukri")


class NaukriSource(JobSource):
    name = "Naukri"

    def fetch_listings(self) -> list[JobListing]:
        rows = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.naukri.com/software-developer-fresher-jobs",
            "Origin": "https://www.naukri.com",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "appid": "109",
            "systemid": "Naukri",
            "clientid": "d3skt0p",
        }
        breaker_threshold = max(1, int(os.environ.get("SOURCE_406_BREAKER_THRESHOLD", "3")))
        consecutive_block_failures = 0

        for term in config.NAUKRI_SEARCH_TERMS:
            if consecutive_block_failures >= breaker_threshold:
                log.warning(
                    "Naukri circuit breaker opened after %s consecutive 406 responses; "
                    "skipping remaining queries for this run",
                    consecutive_block_failures,
                )
                break

            params = {
                "noOfResults": 20, "urlType": "search_by_key_loc", "searchType": "adv",
                "keyword": term, "location": "bangalore", "k": term, "l": "bangalore",
                "experience": 0,
            }
            try:
                resp = requests.get(
                    "https://www.naukri.com/jobapi/v3/search",
                    headers=headers,
                    params=params,
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                consecutive_block_failures = 0
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 406:
                    consecutive_block_failures += 1
                    log.warning(
                        "fetch failed for '%s' (406 Not Acceptable), consecutive=%s/%s",
                        term,
                        consecutive_block_failures,
                        breaker_threshold,
                    )
                else:
                    consecutive_block_failures = 0
                    log.warning("fetch failed for '%s': %s", term, exc)
                continue
            except Exception as exc:
                consecutive_block_failures = 0
                log.warning("fetch failed for '%s': %s", term, exc)
                continue

            for job in data.get("jobDetails", []):
                job_id = job.get("jobId", "")
                job_url = job.get("staticUrl", "") or (f"https://www.naukri.com/job-listings-{job_id}" if job_id else "")
                if not job_url:
                    continue
                placeholders = job.get("placeholders", {})
                location = placeholders.get("location", "India") if isinstance(placeholders, dict) else "India"
                rows.append(JobListing(
                    job_url=job_url, title=job.get("title", ""), company=job.get("companyName", ""),
                    location=location, description=job.get("jobDescription", "") or job.get("title", ""),
                    source=self.name,
                ))
            time.sleep(1)
        return rows
