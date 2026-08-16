"""
LinkedIn recruiter-post scraping — optional, OFF BY DEFAULT, and the
highest-risk source in this project. Only activates if LINKEDIN_LI_AT_COOKIE
is set. Uses a real personal session cookie against an undocumented
internal API. LinkedIn actively pursues legal action against scrapers and
can flag/suspend accounts used this way — this trade-off was made
knowingly, at explicit user request. If it ever causes account trouble,
just delete the LINKEDIN_LI_AT_COOKIE secret; this source turns itself off
with no other changes needed, and everything else keeps working.
"""
import time
import requests

import config
from models import JobListing
from sources.base import JobSource
from utils.logging_setup import get_logger

log = get_logger("linkedin_posts")


class LinkedInPostsSource(JobSource):
    name = "LinkedIn Posts"

    def fetch_listings(self) -> list[JobListing]:
        if not config.LINKEDIN_LI_AT_COOKIE:
            log.info("LINKEDIN_LI_AT_COOKIE not set — skipping")
            return []

        rows = []
        session = requests.Session()
        session.cookies.set("li_at", config.LINKEDIN_LI_AT_COOKIE, domain=".linkedin.com")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "x-restli-protocol-version": "2.0.0",
        }

        try:
            session.get("https://www.linkedin.com/feed/", headers=headers, timeout=15, allow_redirects=True)
            jsessionid = session.cookies.get("JSESSIONID", "").strip('"')
            if not jsessionid:
                log.warning("no JSESSIONID received — cookie likely expired or invalid")
                return []
            headers["csrf-token"] = jsessionid
        except requests.exceptions.TooManyRedirects:
            log.warning("too many redirects — LINKEDIN_LI_AT_COOKIE is expired or invalid; get a fresh li_at value")
            return []
        except Exception as exc:
            log.warning(f"session init failed: {exc}")
            return []

        for term in config.LINKEDIN_POST_SEARCH_TERMS:
            try:
                resp = session.get(
                    "https://www.linkedin.com/voyager/api/search/dash/clusters",
                    headers=headers,
                    params={
                        "decorationId": "com.linkedin.voyager.dash.deco.search.SearchClusterCollection-166",
                        "origin": "GLOBAL_SEARCH_HEADER", "q": "all",
                        "query": f"(keywords:{term},flagshipSearchIntent:SEARCH_SRP,queryParameters:(resultType:List(CONTENT)))",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 400:
                    log.warning(f"search failed for '{term}' (400 Bad Request). Firecrawl will be used as a fallback.")
                else:
                    log.warning(f"search failed for '{term}': {e}")
                continue
            except Exception as exc:
                log.warning(f"search failed for '{term}': {exc}")
                continue

            for item in data.get("included", []):
                commentary = item.get("commentary", {})
                text = commentary.get("text", {}).get("text", "") if isinstance(commentary, dict) else ""
                if not text or len(text) < 40:
                    continue
                actor = item.get("actor", {}) if isinstance(item.get("actor"), dict) else {}
                author_name = actor.get("name", {}).get("text", "") if isinstance(actor.get("name"), dict) else ""
                permalink = item.get("permalink", "") or item.get("updateMetadata", {}).get("urn", "")
                if not permalink:
                    continue
                job_url = permalink if str(permalink).startswith("http") else f"https://www.linkedin.com/feed/update/{permalink}"
                rows.append(JobListing(
                    job_url=job_url, title=text[:80], company=author_name, location="India",
                    description=text, source=self.name,
                ))
            time.sleep(2)

        if not rows:
            log.info("0 results — cookie may have expired or LinkedIn changed the API")
        return rows
