"""Company career pages via Greenhouse's public API — genuinely reliable,
unlike Wellfound/Naukri, since this is a real documented public endpoint.
Only covers companies configured in config.GREENHOUSE_BOARDS."""
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
        for company_name, token in config.GREENHOUSE_BOARDS.items():
            try:
                resp = requests.get(
                    f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                    params={"content": "true"}, timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                log.warning(f"fetch failed for '{company_name}' (token '{token}'): {exc}")
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
