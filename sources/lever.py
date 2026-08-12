"""Company career pages via Lever's public API — same reliability profile
as Greenhouse. Only covers companies configured in config.LEVER_BOARDS."""
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
        for company_name, token in config.LEVER_BOARDS.items():
            try:
                resp = requests.get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"}, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    log.warning(f"fetch failed for '{company_name}' (token '{token}'): 404 Not Found")
                else:
                    log.warning(f"fetch failed for '{company_name}' (token '{token}'): {e}")
                continue
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    log.warning(f"fetch failed for '{company_name}' (token '{token}'): 404 Not Found")
                else:
                    log.warning(f"fetch failed for '{company_name}' (token '{token}'): {e}")
                continue
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    log.warning(f"fetch failed for '{company_name}' (token '{token}'): 404 Not Found")
                else:
                    log.warning(f"fetch failed for '{company_name}' (token '{token}'): {e}")
                continue
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    log.warning(f"fetch failed for '{company_name}' (token '{token}'): 404 Not Found")
                else:
                    log.warning(f"fetch failed for '{company_name}' (token '{token}'): {e}")
                continue
            except Exception as exc:
                log.warning(f"fetch failed for '{company_name}' (token '{token}'): {exc}")
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
