"""Canonical job normalization, cross-source deduplication, and ranking helpers."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from models import JobListing

_TRACKING_KEYS = {"ref", "src", "trk", "gclid", "fbclid", "mc_cid", "mc_eid"}
_LOCATION_ALIASES = {"bangalore": "bengaluru", "bengaluru": "bengaluru", "bombay": "mumbai", "gurgaon": "gurugram", "new delhi": "delhi"}
_STOPWORDS = {"the", "a", "an", "and", "of", "for", "to", "in", "at", "on", "with"}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def normalize_title(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\b(remote|hybrid|onsite|on-site)\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_company(value: str) -> str:
    value = re.sub(r"[^a-z0-9& ]+", " ", normalize_text(value))
    return re.sub(r"\s+", " ", value).strip()


def normalize_location(value: str) -> str:
    value = normalize_text(value)
    for source, target in _LOCATION_ALIASES.items():
        value = re.sub(rf"\b{re.escape(source)}\b", target, value)
    return re.sub(r"\s+", " ", value).strip()


def canonical_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in _TRACKING_KEYS and not k.lower().startswith("utm_")]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def normalize_posting_date(value: str) -> tuple[str, str]:
    raw = normalize_text(value)
    if not raw:
        return "", "UNKNOWN"
    now = datetime.now(timezone.utc)
    m = re.search(r"(\d+)\s*(minute|hour|day)s?\s+ago", raw)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        seconds = amount * {"minute": 60, "hour": 3600, "day": 86400}[unit]
        dt = now.fromtimestamp(now.timestamp() - seconds, tz=timezone.utc)
        age_days = seconds / 86400
        return dt.isoformat(), ("FRESH" if age_days <= 1 else "RECENT" if age_days <= 7 else "STALE")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            age_days = max(0.0, (now - dt).total_seconds() / 86400)
            return dt.date().isoformat(), ("FRESH" if age_days <= 1 else "RECENT" if age_days <= 7 else "STALE")
        except ValueError:
            continue
    return value.strip(), "UNKNOWN"


def description_quality(listing: JobListing) -> int:
    desc = normalize_text(listing.description)
    score = min(30, len(desc) // 100)
    keywords = ("requirements", "qualifications", "responsibilities", "experience", "skills")
    score += min(30, 5 * sum(keyword in desc for keyword in keywords))
    score += 10 if listing.title else 0
    score += 10 if listing.company else 0
    score += 10 if listing.location else 0
    score += 10 if listing.posting_date else 0
    return min(100, score)


def data_quality_score(listing: JobListing) -> int:
    score = 20 if canonical_url(listing.job_url) else 0
    score += 15 if listing.title.strip() else 0
    score += 15 if listing.company.strip() else 0
    score += 10 if listing.location.strip() else 0
    score += min(20, len((listing.description or "").strip()) // 150)
    score += 10 if listing.posting_date else 0
    score += 5 if listing.employment_type else 0
    score += 5 if description_quality(listing) >= 60 else 0
    return min(100, score)


def _job_fingerprint(listing: JobListing) -> str:
    canonical = canonical_url(listing.job_url)
    if canonical:
        return "url:" + hashlib.sha256(canonical.encode()).hexdigest()
    payload = "|".join((normalize_company(listing.company), normalize_title(listing.title), normalize_location(listing.location), normalize_text(listing.description)[:1000]))
    return "content:" + hashlib.sha256(payload.encode()).hexdigest()


def _similar_identity(listing: JobListing) -> str:
    return "|".join((normalize_company(listing.company), normalize_title(listing.title), normalize_location(listing.location)))


def deduplicate_jobs(listings: list[JobListing]) -> tuple[list[JobListing], int]:
    """Collapse exact duplicates and only very strong cross-source matches."""
    groups: dict[str, list[JobListing]] = defaultdict(list)
    for listing in listings:
        groups[_job_fingerprint(listing)].append(listing)
    merged = [max(members, key=data_quality_score) for members in groups.values()]

    by_identity: dict[str, JobListing] = {}
    for listing in merged:
        key = _similar_identity(listing)
        existing = by_identity.get(key)
        if existing is None:
            by_identity[key] = listing
            continue
        a = set(normalize_text(existing.description).split()) - _STOPWORDS
        b = set(normalize_text(listing.description).split()) - _STOPWORDS
        intersection = len(a & b)
        union = len(a | b)
        containment = intersection / max(1, min(len(a), len(b)))
        jaccard = intersection / max(1, union)
        # A short syndicated description can be a subset of the expanded source.
        # Require strong token containment or broad overlap before collapsing records.
        if a and b and (containment >= 0.50 or jaccard >= 0.50):
            if data_quality_score(listing) > data_quality_score(existing):
                by_identity[key] = listing
        else:
            unique_key = key + "|" + canonical_url(listing.job_url)
            by_identity[unique_key] = listing

    result = list(by_identity.values())
    return result, max(0, len(listings) - len(result))


def relevance_score(listing: JobListing) -> float:
    """Deterministic pre-AI ranking using profile relevance, never company prestige."""
    text = " ".join((normalize_text(listing.title), normalize_text(listing.description)))
    title = normalize_title(listing.title)
    score = 0.0
    role_terms = ("software engineer", "software developer", "full stack", "frontend", "backend", "react", "node.js", "javascript", "typescript", "mern", "sde")
    stack_terms = ("react", "react.js", "node", "node.js", "javascript", "typescript", "mongodb", "express", "sql")
    preferred_locations = ("bengaluru", "pune", "hyderabad", "gurugram", "noida", "mumbai", "chennai", "remote", "india")
    fresher_terms = ("fresher", "entry level", "entry-level", "new grad", "graduate", "0-1", "0–1", "0-2", "0–2", "junior")
    senior_terms = ("senior", "staff", "principal", "lead", "manager", "architect")
    score += min(30, 6 * sum(term in title for term in role_terms))
    score += min(25, 5 * sum(term in text for term in stack_terms))
    score += min(15, 5 * sum(term in normalize_location(listing.location) for term in preferred_locations))
    score += min(15, 5 * sum(term in text for term in fresher_terms))
    score -= min(30, 10 * sum(term in title for term in senior_terms))
    _, freshness = normalize_posting_date(listing.posting_date)
    score += {"FRESH": 15, "RECENT": 10, "STALE": -5, "UNKNOWN": 0}[freshness]
    score += data_quality_score(listing) * 0.15
    return round(score, 3)


def rank_candidates(listings: list[JobListing]) -> list[JobListing]:
    for listing in listings:
        listing.prefilter_score = int(round(relevance_score(listing)))
    return sorted(listings, key=lambda item: (item.prefilter_score, data_quality_score(item), normalize_text(item.title)), reverse=True)


def quality_summary(raw_count: int, deduped: list[JobListing], eligible: list[JobListing], selected: list[JobListing], duplicates_removed: int) -> dict:
    buckets = {"FRESH": 0, "RECENT": 0, "STALE": 0, "UNKNOWN": 0}
    for listing in deduped:
        _, bucket = normalize_posting_date(listing.posting_date)
        buckets[bucket] += 1
    qualities = [data_quality_score(item) for item in deduped]
    return {
        "raw_jobs": raw_count,
        "normalized_jobs": len(deduped),
        "duplicates_removed": duplicates_removed,
        "eligible_jobs": len(eligible),
        "ai_candidates": len(selected),
        "fresh_jobs": buckets["FRESH"],
        "recent_jobs": buckets["RECENT"],
        "stale_jobs": buckets["STALE"],
        "unknown_date_jobs": buckets["UNKNOWN"],
        "average_data_quality": round(sum(qualities) / len(qualities), 2) if qualities else 0.0,
    }
