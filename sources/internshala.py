"""Internshala — server-rendered HTML, safe to plain-scrape. Anchored on
the stable '/internship/detail/' URL pattern rather than a CSS class,
since a class-based selector broke once already when Internshala's markup
shifted. Unpaid internships are dropped before anything else touches them."""
import time
import requests
from bs4 import BeautifulSoup

import config
from models import JobListing
from sources.base import JobSource
from utils.logging_setup import get_logger

log = get_logger("internshala")


class InternshalaSource(JobSource):
    name = "Internshala"

    def fetch_listings(self) -> list[JobListing]:
        rows = []
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        for term in config.INTERNSHALA_SEARCH_TERMS:
            url = f"https://internshala.com/internships/{term}-internship/"
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
            except Exception as exc:
                log.warning(f"fetch failed for '{term}': {exc}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            seen_this_page = set()
            for link_el in soup.select('a[href*="/internship/detail/"]'):
                title = link_el.get_text(strip=True)
                href = link_el.get("href", "")
                if not title or not href:
                    continue
                full_url = f"https://internshala.com{href}" if href.startswith("/") else href
                if full_url in seen_this_page:
                    continue
                seen_this_page.add(full_url)

                container = link_el.find_parent(["div", "li"])
                for _ in range(3):
                    if container is None:
                        break
                    text = container.get_text(" ", strip=True)
                    if "₹" in text or "unpaid" in text.lower():
                        break
                    container = container.find_parent(["div", "li"])
                context_text = container.get_text(" ", strip=True) if container else ""

                if "unpaid" in context_text.lower():
                    continue

                rows.append(JobListing(
                    job_url=full_url, title=title, company="", location="India",
                    description=context_text[:500] if context_text else title,
                    source=self.name,
                ))
            time.sleep(1)
        return rows
