"""Arbeitnow — free public job board API, no auth, no rate limiting, no
anti-bot. Genuinely one of the least fragile sources here. Skews toward
remote/EU-friendly roles rather than India-specific ones, but a decent
chunk of listings are remote-open and fresher-friendly, so it's worth
the coverage. Filtered client-side by keyword since the API has no
server-side search."""
import requests

import config
from models import JobListing
from sources.base import JobSource
from utils.logging_setup import get_logger

log = get_logger("arbeitnow")


class ArbeitnowSource(JobSource):
    name = "Arbeitnow"

    def fetch_listings(self) -> list[JobListing]:
        rows = []
        try:
            resp = requests.get("https://arbeitnow.com/api/job-board-api", timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning(f"fetch failed: {exc}")
            return rows

        keywords = [k.lower() for k in config.ARBEITNOW_KEYWORDS]
        for job in data.get("data", []):
            title = job.get("title", "") or ""
            tags = " ".join(job.get("tags", []) or [])
            haystack = f"{title} {tags}".lower()
            if not any(k in haystack for k in keywords):
                continue
            rows.append(JobListing(
                job_url=job.get("url", ""), title=title,
                company=job.get("company_name", ""),
                location=job.get("location", "") or ("Remote" if job.get("remote") else "India"),
                description=job.get("description", "") or title, source=self.name,
            ))
        return rows
