"""RemoteOK — free public API, no auth, no rate limiting. First element of
the response is always a legal-notice object, not a job, so it's skipped.
Global remote listings only; filtered client-side by keyword/tag since the
API has no server-side search. Needs a real-looking User-Agent or it
occasionally 403s."""
import requests

import config
from models import JobListing
from sources.base import JobSource
from utils.logging_setup import get_logger

log = get_logger("remoteok")


class RemoteOKSource(JobSource):
    name = "RemoteOK"

    def fetch_listings(self) -> list[JobListing]:
        rows = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }
        try:
            resp = requests.get("https://remoteok.com/api", headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning(f"fetch failed: {exc}")
            return rows

        keywords = [k.lower() for k in config.REMOTEOK_KEYWORDS]
        for job in data:
            if not isinstance(job, dict) or "position" not in job:
                continue  # skips the legal-notice object at index 0
            title = job.get("position", "") or ""
            tags = " ".join(job.get("tags", []) or [])
            haystack = f"{title} {tags}".lower()
            if not any(k in haystack for k in keywords):
                continue
            job_url = job.get("url", "")
            if job_url and job_url.startswith("/"):
                job_url = f"https://remoteok.com{job_url}"
            rows.append(JobListing(
                job_url=job_url, title=title, company=job.get("company", ""),
                location=job.get("location", "") or "Remote",
                description=job.get("description", "") or title, source=self.name,
            ))
        return rows
