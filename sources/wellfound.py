"""Wellfound — best-effort, likely returns 0 most runs. Wellfound uses
DataDome/Cloudflare anti-bot protection specifically to block scrapers;
this attempts to parse the public role page's embedded __NEXT_DATA__
without logging in, which sometimes works and often doesn't. Making this
reliable would need a paid residential-proxy/anti-bot-bypass service — a
real cost, not a code fix. A 0-listing result here is expected, not a bug."""
import time
import json
import requests
from bs4 import BeautifulSoup

import config
from models import JobListing
from sources.base import JobSource
from utils.logging_setup import get_logger

log = get_logger("wellfound")


def _find_job_like_dicts(node, found=None, depth=0, max_depth=25):
    if found is None:
        found = []
    if depth > max_depth:
        return found
    if isinstance(node, dict):
        if any(k in node for k in ("title", "jobTitle")) and any(k in node for k in ("slug", "jobListingSlug", "id")):
            found.append(node)
        for value in node.values():
            _find_job_like_dicts(value, found, depth + 1, max_depth)
    elif isinstance(node, list):
        for item in node:
            _find_job_like_dicts(item, found, depth + 1, max_depth)
    return found


class WellfoundSource(JobSource):
    name = "Wellfound"

    def fetch_listings(self) -> list[JobListing]:
        rows = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }
        for slug in config.WELLFOUND_ROLE_SLUGS:
            try:
                resp = requests.get(f"https://wellfound.com/role/{slug}", headers=headers, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                script_tag = soup.find("script", id="__NEXT_DATA__")
                if not script_tag or not script_tag.string:
                    log.warning(f"'{slug}': no __NEXT_DATA__ — likely blocked (DataDome/CAPTCHA)")
                    continue
                state = json.loads(script_tag.string)
                for job in _find_job_like_dicts(state):
                    title = job.get("title") or job.get("jobTitle") or ""
                    slug_val = job.get("slug") or job.get("jobListingSlug") or job.get("id") or ""
                    if not title or not slug_val:
                        continue
                    job_url = f"https://wellfound.com/jobs/{slug_val}" if not str(slug_val).startswith("http") else slug_val
                    rows.append(JobListing(
                        job_url=job_url, title=title,
                        company=job.get("companyName") or job.get("startupName") or "",
                        location=job.get("locationNames") or job.get("location") or "India",
                        description=job.get("description") or title, source=self.name,
                    ))
            except Exception as exc:
                log.warning(f"fetch failed for '{slug}': {exc}")
            time.sleep(1)

        if not rows:
            log.info("0 listings — most likely blocked by anti-bot protection, not a code bug")
        return rows
