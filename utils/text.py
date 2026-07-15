"""Text-parsing helpers shared across sources and enrichment: email
extraction, company-domain guessing, and job-link extraction from freeform
description text (used by the YouTube source)."""
import re

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
URL_IN_TEXT_REGEX = re.compile(r"https?://[^\s\)\]\>\"']+")

NON_JOB_LINK_DOMAINS = [
    "instagram.com", "t.me", "telegram.me", "wa.me", "chat.whatsapp.com",
    "facebook.com", "fb.com", "twitter.com", "x.com/", "youtube.com/watch",
    "youtube.com/@", "youtube.com/channel", "youtu.be", "linkedin.com/in/",
    "linktr.ee",
]

_COMPANY_SUFFIXES = [
    " pvt ltd", " pvt. ltd.", " private limited", " limited", " llp",
    " inc.", " inc", " llc", " technologies", " technology", " labs",
    " solutions", " services", " systems", " india", " co.", " ltd",
]


def extract_email_from_text(text: str) -> str:
    if not text:
        return ""
    match = EMAIL_REGEX.search(text)
    return match.group(0) if match else ""


def guess_company_domain(company_name: str) -> str:
    name = (company_name or "").lower().strip()
    for suffix in _COMPANY_SUFFIXES:
        name = name.replace(suffix, "")
    name = re.sub(r"[^a-z0-9]", "", name)
    return f"{name}.com" if name else ""


def extract_job_links_from_description(description: str, fallback_title: str) -> list:
    """Walks a description line by line for real job/apply links, pairing
    each with its surrounding line as a title guess. Filters out obvious
    social/messaging/self-promo noise via a blocklist (not a keyword
    whitelist) — everything not explicitly blocked is kept."""
    results, seen = [], set()
    for line in description.split("\n"):
        for raw_url in URL_IN_TEXT_REGEX.findall(line):
            url = raw_url.rstrip(").,;:")
            if url in seen or any(d in url.lower() for d in NON_JOB_LINK_DOMAINS):
                continue
            seen.add(url)
            context = line.replace(raw_url, "").strip(" -:|\t•—")
            results.append((url, context if context else fallback_title))
    return results
