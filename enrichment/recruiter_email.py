"""
Recruiter/company email enrichment — a three-tier chain, each tried only
if the previous comes up empty:
  1. JD-published email
  2. Hunter.io generic domain lookup
  3. Apollo.io named-person search + enrichment

Apollo access is optional. A 401/403 means the configured key is invalid or
lacks the endpoint scope/plan, so Apollo is disabled for the remainder of the
current run instead of repeatedly treating the authorization failure as a
transient lookup error.
"""
import time
import requests

import config
from models import JobListing
from utils.text import extract_email_from_text, guess_company_domain
from utils.logging_setup import get_logger

log = get_logger("enrichment")
_apollo_disabled_for_run = False


def _hunter_domain_search(domain: str) -> str:
    if not domain:
        return ""
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": config.HUNTER_API_KEY, "limit": 1},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        emails = data.get("data", {}).get("emails", [])
        if emails:
            return emails[0].get("value", "")
        pattern = data.get("data", {}).get("pattern", "")
        if pattern:
            return f"(pattern: {pattern}@{domain})"
    except Exception as exc:
        log.warning(f"hunter.io lookup failed for '{domain}': {exc}")
    return ""


def _apollo_find_contact(company_name: str, domain: str) -> str:
    """Find and enrich one recruiter/HR contact; authorization failures disable Apollo for this run."""
    global _apollo_disabled_for_run
    if not domain or _apollo_disabled_for_run:
        return ""

    try:
        search_resp = requests.post(
            "https://api.apollo.io/api/v1/mixed_people/api_search",
            headers={
                "X-Api-Key": config.APOLLO_API_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Cache-Control": "no-cache",
            },
            json={
                "q_organization_domains_list": [domain],
                "person_titles": config.APOLLO_TARGET_TITLES,
                "per_page": 1,
                "page": 1,
            },
            timeout=15,
        )
        if search_resp.status_code in {401, 403}:
            _apollo_disabled_for_run = True
            log.warning(
                "Apollo disabled for this run: HTTP %s for people search. "
                "Check the API key's endpoint scope/plan before re-enabling Apollo.",
                search_resp.status_code,
            )
            return ""
        search_resp.raise_for_status()
        people = search_resp.json().get("people", [])
        if not people:
            return ""

        person_id = people[0].get("id", "")
        if not person_id:
            return ""

        enrich_resp = requests.post(
            "https://api.apollo.io/api/v1/people/match",
            headers={
                "X-Api-Key": config.APOLLO_API_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Cache-Control": "no-cache",
            },
            json={"id": person_id, "reveal_personal_emails": False},
            timeout=15,
        )
        if enrich_resp.status_code in {401, 403}:
            _apollo_disabled_for_run = True
            log.warning(
                "Apollo disabled for this run: HTTP %s for people enrichment. "
                "Check the API key's endpoint scope/plan before re-enabling Apollo.",
                enrich_resp.status_code,
            )
            return ""
        enrich_resp.raise_for_status()

        person = enrich_resp.json().get("person", {})
        email = person.get("email", "")
        if not email:
            return ""
        name, title = person.get("name", ""), person.get("title", "")
        return f"{email} ({name}, {title}, Apollo)" if name else f"{email} (Apollo)"
    except requests.RequestException as exc:
        log.warning(f"apollo lookup failed for '{company_name}' ({domain}): {exc}")
        return ""
    except (TypeError, ValueError, KeyError) as exc:
        log.warning(f"apollo response parsing failed for '{company_name}' ({domain}): {exc}")
        return ""


def enrich_with_emails(listings: list[JobListing]) -> list[JobListing]:
    global _apollo_disabled_for_run
    _apollo_disabled_for_run = False
    hunter_calls_used = 0
    apollo_calls_used = 0

    for listing in listings:
        jd_email = extract_email_from_text(listing.description)
        if jd_email:
            listing.recruiter_email = jd_email
            continue

        found = ""
        if config.HUNTER_API_KEY and hunter_calls_used < config.HUNTER_MAX_CALLS_PER_RUN:
            domain = guess_company_domain(listing.company)
            result = _hunter_domain_search(domain)
            hunter_calls_used += 1
            if result:
                found = f"{result} (generic, Hunter)"
            time.sleep(0.5)

        if (
            not found
            and config.APOLLO_API_KEY
            and apollo_calls_used < config.APOLLO_MAX_CALLS_PER_RUN
            and not _apollo_disabled_for_run
        ):
            domain = guess_company_domain(listing.company)
            result = _apollo_find_contact(listing.company, domain)
            apollo_calls_used += 1
            if result:
                found = result
            time.sleep(0.5)

        listing.recruiter_email = found

    return listings
