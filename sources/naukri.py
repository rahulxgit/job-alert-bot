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
            for location in config.PREFERRED_LOCATIONS:
                if consecutive_block_failures >= breaker_threshold:
                    log.warning(f"Naukri API blocked (HTTP 406 Not Acceptable) after {consecutive_block_failures} consecutive failures. Stopping further requests.")
                    return rows

                params = {
                    "noOfResults": 20, "urlType": "search_by_key_loc", "searchType": "adv",
                    "keyword": term, "location": location, "k": term, "l": location,
                    "experience": 0,
                }
                data = None
                for attempt in range(3):
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
                        break
                    except requests.exceptions.HTTPError as exc:
                        status = exc.response.status_code if exc.response is not None else None
                        if status == 406:
                            consecutive_block_failures += 1
                            log.warning(
                                "fetch failed for '%s' in '%s' (406 Not Acceptable), consecutive=%s/%s",
                                term,
                                location,
                                consecutive_block_failures,
                                breaker_threshold,
                            )
                            break
                        elif status in (429, 500, 502, 503, 504) and attempt < 2:
                            time.sleep(2 ** attempt)
                            continue
                        else:
                            consecutive_block_failures = 0
                            log.warning("fetch failed for '%s' in '%s': %s", term, location, exc)
                            break
                    except Exception as exc:
                        if attempt < 2:
                            time.sleep(2 ** attempt)
                            continue
                        consecutive_block_failures = 0
                        log.warning("fetch failed for '%s' in '%s': %s", term, location, exc)
                        break
                
                if not data:
                    continue

                for job in data.get("jobDetails", []):
                    job_id = job.get("jobId", "")
                    job_url = job.get("staticUrl", "") or (f"https://www.naukri.com/job-listings-{job_id}" if job_id else "")
                    if not job_url:
                        continue
                    placeholders = job.get("placeholders", {})
                    job_location = placeholders.get("location", location) if isinstance(placeholders, dict) else location
                    rows.append(JobListing(
                        job_url=job_url, title=job.get("title", ""), company=job.get("companyName", ""),
                        location=job_location, description=job.get("jobDescription", "") or job.get("title", ""),
                        source=self.name,
                    ))
                time.sleep(1)
        return rows
