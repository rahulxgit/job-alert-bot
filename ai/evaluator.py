import os
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

"""Job-fit evaluation driven by the canonical master profile."""

import config
from models import FitVerdict, JobListing
from ai.gemini_provider import GeminiProvider
from ai.groq_provider import GroqProvider
from ai.gateway_provider import GatewayProvider
from ai.profile import build_candidate_profile
from ai.metrics import MetricsCoordinator
from ai.checkpoint import CHECKPOINT_VERSION, compatible, evaluation_key, profile_hash, checkpoint_identity
from ai.provider_limiter import ProviderBackoff
from ai.state import EvaluationState, QUEUED, EVALUATING, EVALUATED, PASSED, REJECTED, RETRYABLE_ERROR, PERMANENT_ERROR, DEADLINE_EXCEEDED
from ai.state_store import AIStateStore
from ai.state_migration import migrate_legacy_progress, migrate_legacy_retry_jobs
from utils.logging_setup import get_logger

log = get_logger("evaluator")
_gemini = GeminiProvider()
_groq = GroqProvider()
_gateway = GatewayProvider()
_candidate_profile = None
FAILED_AI_JOBS_PATH = Path("failed-ai-jobs.json")
AI_PROGRESS_PATH = Path("run-artifacts/ai-progress.json")
AI_PROGRESS_VERSION = CHECKPOINT_VERSION
AI_MAX_ATTEMPTS_PER_CANDIDATE = max(1, int(getattr(config, "AI_EVALUATION_MAX_ATTEMPTS_PER_CANDIDATE", 3)))
AI_RETRY_DELAY_SECONDS = max(1.0, float(getattr(config, "AI_EVALUATION_RETRY_DELAY_SECONDS", 15)))
AI_MAX_RETRY_DELAY_SECONDS = max(AI_RETRY_DELAY_SECONDS, float(getattr(config, "AI_EVALUATION_MAX_RETRY_DELAY_SECONDS", 60)))
_gemini_backoff = ProviderBackoff()
_groq_backoff = ProviderBackoff()
_gateway_backoff = ProviderBackoff()


def _profile() -> str:
    global _candidate_profile
    if _candidate_profile is None:
        _candidate_profile = build_candidate_profile()
    return _candidate_profile


def _build_prompt(listing: JobListing) -> str:
    return f"""You are Rahul Kumar's evidence-based job-fit evaluator.

CANONICAL CANDIDATE PROFILE
===========================
{_profile()}

JOB LISTING
===========
Title: {listing.title or ''}
Company: {listing.company or ''}
Location: {listing.location or ''}
Source: {listing.source or ''}
Description:
{(listing.description or '')[:10000]}

EVALUATION INSTRUCTIONS
=======================
- The canonical master profile is the ONLY factual source for the candidate.
- Never invent or assume a skill, technology, job, duration, project, achievement, CP statistic, education fact, certification, motivation, or application detail that is absent.
- Use all relevant evidence in the profile: identity/career stage, education, experience, skills, AI engineering, projects, leadership, achievements, competitive-programming profile, location/preferences, target roles/company types/industries, professional positioning, narrative, application/cover-letter/motivation context, and other canonical fields when relevant.
- Preserve explicit uncertainty/conflict notes rather than silently correcting them.
- Compare hard requirements separately from preferred requirements.
- Mandatory professional experience above 1 year is normally ineligible for this entry-level 2026 candidate; 2+ years and senior/lead/staff/principal/manager roles should be rejected unless the JD explicitly welcomes fresh graduates.
- A missing preferred skill is a gap, not an automatic rejection.
- Direct evidence should score higher than merely adjacent/transferable evidence.
- For technical fit, compare languages, frameworks, backend, databases, APIs, architecture, AI/LLM, cloud/devops, testing, tooling, and other concrete JD requirements.
- For project fit, identify the most relevant canonical projects and concrete engineering evidence; do not reward project quantity alone.
- For education fit, check degree/branch, graduation timing, CGPA constraints, and stated eligibility; do not hard-exclude B.Tech Biomedical unless explicitly banned (many roles accept 'any engineering branch').
- For experience fit, distinguish internship/production project evidence from full-time professional experience.
- Leadership, achievements, and CP data can improve fit when relevant but cannot override hard eligibility failures.
- Location fit must use the profile's actual preferences; do not invent relocation willingness.
- Company/industry preferences are a modest factor, not a standalone rejection reason.
- If a material requirement cannot be verified, say so in gaps instead of assuming it.
- Reasons and gaps must mention specific candidate/JD evidence.
- WALK-IN DETECTION: If the JD mentions a walk-in/hiring drive, set is_walkin to true and extract walkin_date and venue.

SCORING
=======
role_match: 0-25
experience_match: 0-20
technical_match: 0-25
project_match: 0-10
education_match: 0-10
location_match: 0-5
company_quality: 0-5
fit_score MUST equal the sum of these seven scores and be 0-100.
If it is a walk-in drive in Pune for a software engineer role, boost location_match to 5 and role_match to 25.

DECISION
========
strong_match = strong alignment with no material hard blocker
good_match = solid alignment with manageable gaps
weak_match = partial alignment with material gaps/uncertainty
reject = hard eligibility blocker, seniority mismatch, or very poor alignment

OUTPUT
======
Return ONLY valid JSON. No markdown fences or surrounding prose.
All numeric fields are integers. why and gaps are arrays of at most 3 short
strings each (under ~15 words) — be concise, not exhaustive, so the response
stays well within the output token budget and is never truncated mid-JSON.

{{
  "fit_score": 0,
  "role_match": 0,
  "experience_match": 0,
  "technical_match": 0,
  "project_match": 0,
  "education_match": 0,
  "location_match": 0,
  "company_quality": 0,
  "decision": "strong_match|good_match|weak_match|reject",
  "is_fresher_appropriate": true,
  "why": ["specific evidence"],
  "gaps": ["specific gap or uncertainty"],
  "is_walkin": false,
  "walkin_date": "YYYY-MM-DD or empty",
  "venue": ""
}}
"""


def _parse_experience(text: str) -> dict:
    text_lower = text.lower()
    res = {"min_years": 0, "max_years": 0, "required": False, "preferred": False, "graduate_friendly": False, "eligible_for_rahul": True, "reason": ""}
    graduate_signals = [
        "new grad", "fresher", "0-1 years", "0-1 yrs", "0-1 yr", "0 to 1", "0-2 years", "0-2 yrs", "0-2 yr", "0 to 2", "0 - 2", "0 – 2", "0–1", "0–2", "up to 1 year", "1 year experience", "1+ years", "final-year", "2026 graduate", "graduate", "entry level", "entry-level",
    ]
    if any(sig in text_lower for sig in graduate_signals):
        res["graduate_friendly"] = True

    req_match = re.search(r"\b([2-9]|1[0-9])\+?\s*(?:\+|to|-|–|\s)*\s*(?:years?|yrs?)\s*(?:of\s*experience)?\b", text_lower)
    if req_match:
        years = int(req_match.group(1))
        res["min_years"] = years
        preferred_match = re.search(r"\b([2-9]|1[0-9])\+?\s*(?:\+|to|-|–|\s)*\s*(?:years?|yrs?).{0,30}(?:preferred|a plus|nice to have|advantage|bonus)\b", text_lower)
        if preferred_match:
            res["preferred"] = True
        else:
            res["required"] = True
            if years > 1 and not res["graduate_friendly"]:
                res["eligible_for_rahul"] = False
                res["reason"] = f"Mandatory experience ({years}+ years) exceeds 1 year and no fresher signal found."

    seniority_hits = sum(term in text_lower for term in config.SENIORITY_EXCLUSIONS)
    if seniority_hits >= 2 and not res["graduate_friendly"]:
        res["eligible_for_rahul"] = False
        res["reason"] = "Role appears too senior based on title/description keywords."
    return res


try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

def _contains_any(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term.lower() in text]

def _contains_any_word(text: str, terms: list[str]) -> list[str]:
    found = []
    for term in terms:
        pattern = r'\b' + re.escape(term.lower()) + r'\b'
        if re.search(pattern, text):
            found.append(term)
    return found


def _location_score(text: str) -> tuple[int, bool]:
    normalized = text.lower()
    preferred_hits = _contains_any(normalized, config.PREFERRED_LOCATIONS)
    if preferred_hits:
        return min(5, 2 + len(preferred_hits)), False
    if "remote" in normalized or "work from home" in normalized or "wfh" in normalized:
        return 5, False
    outside_hits = _contains_any(normalized, config.NON_PREFERRED_LOCATION_SIGNALS)
    if outside_hits:
        return 0, True
    return 1, False


def _education_score(text: str) -> tuple[int, bool]:
    normalized = text.lower()
    
    # Reject explicit strict CS-only requirements using robust bounded tokens
    cs_only_pattern = r"\b(?:computer science|cs|b\.?tech in cs|b\.?tech cs|it|information technology)(?: graduates| candidates| engineers| students)? only\b|\bstrictly (?:computer science|cs|it)\b"
    if re.search(cs_only_pattern, normalized):
        return 0, True

    if _contains_any(normalized, config.EDUCATION_OPEN_SIGNALS):
        return 4, False
    return 2, False


def _freshness_score(listing: JobListing) -> tuple[int, bool]:
    raw = (listing.posting_date or "").strip()
    if not raw:
        return 0, False
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", raw)
    if not match:
        return 0, False
    try:
        posted = datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return 0, False
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    age_days = (today - posted).days
    if age_days < 0:
        return 1, False
    if age_days <= 3:
        return 4, False
    if age_days <= 7:
        return 2, False
    if age_days <= config.FRESHNESS_DAYS:
        return 0, False
    return -3, True



try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
from dateutil import parser
from datetime import date, datetime

IST = ZoneInfo("Asia/Kolkata")

WALKIN_DATE_CONTEXT_PATTERNS = [
    r"\bwalk[-\s]?in\b",
    r"\bwalk[-\s]?in interview\b",
    r"\bwalk[-\s]?in drive\b",
    r"\bhiring drive\b",
    r"\binterview date\b",
    r"\bdrive date\b",
    r"\bhiring date\b",
    r"\binterview\b",
    r"\bdrive\b",
]

HISTORICAL_DATE_CONTEXT = [
    r"\bhistorical_event\b",
    r"\bprevious\b",
    r"\blast\b",
    r"\bheld on\b",
    r"\bconducted on\b",
    r"\bpast\b",
    r"\bearlier\b",
    r"\bwas held\b",
    r"\bhad been held\b",
    r"\bestablished\b",
    r"\bfounded\b",
    r"\bincorporated\b",
    r"\bexperience\b",
    r"\bgraduation\b",
    r"\bjoining date\b",
    r"\bdeadline\b"
]

DATE_PATTERN = re.compile(
    r"\b(?:"
    r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}"
    r"|"
    r"\d{1,2}[-/]\d{1,2}[-/]20\d{2}"
    r"|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+20\d{2}"
    r"|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+"
    r"\d{1,2}(?:st|nd|rd|th)?\s+20\d{2}"
    r")\b",
    re.IGNORECASE,
)

RANGE_PATTERN = re.compile(
    r"\b(\d{1,2}(?:st|nd|rd|th)?)\s*(?:-|to|and)\s*(\d{1,2}(?:st|nd|rd|th)?)\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+20\d{2})\b",
    re.IGNORECASE,
)

def _get_min_distance(patterns, text, date_start, date_end):
    min_dist = float('inf')
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            if m.end() <= date_start:
                dist = date_start - m.end()
            elif m.start() >= date_end:
                dist = m.start() - date_end
            else:
                dist = 0
            if dist < min_dist:
                min_dist = dist
    return min_dist

def _extract_walkin_date(text: str) -> tuple[date | None, date | None]:
    if not text:
        return None, None

    candidates = []
    
    blocks = re.split(r'[\n\|]+', text.replace("–", "-").replace("—", "-"))
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
            
        block_mod = re.sub(
            r'\b(previous|earlier|last|past)\s+(walk[-\s]?in|drive|interview|event)\b', 
            r'historical_event', 
            block, 
            flags=re.IGNORECASE
        )
        
        def process_match(start, end, d1, d2):
            pos_dist = _get_min_distance(WALKIN_DATE_CONTEXT_PATTERNS, block_mod, start, end)
            neg_dist = _get_min_distance(HISTORICAL_DATE_CONTEXT, block_mod, start, end)
            if pos_dist > 150:
                return
            if neg_dist <= pos_dist:
                return
            candidates.append((min(d1, d2), max(d1, d2)))

        for match in RANGE_PATTERN.finditer(block_mod):
            try:
                day1_str = re.sub(r'(st|nd|rd|th)', '', match.group(1), flags=re.IGNORECASE)
                day2_str = re.sub(r'(st|nd|rd|th)', '', match.group(2), flags=re.IGNORECASE)
                month_year_str = match.group(3)
                d1 = parser.parse(f"{day1_str} {month_year_str}", fuzzy=True).date()
                d2 = parser.parse(f"{day2_str} {month_year_str}", fuzzy=True).date()
                process_match(match.start(), match.end(), d1, d2)
            except Exception:
                continue

        for match in DATE_PATTERN.finditer(block_mod):
            try:
                d = parser.parse(match.group(0), fuzzy=True).date()
                if any(r[0] <= d <= r[1] for r in candidates if r[1]):
                    continue
                process_match(match.start(), match.end(), d, d)
            except Exception:
                continue

    if not candidates:
        return None, None

    today = datetime.now(IST).date()
    active_or_upcoming = [c for c in candidates if c[1] >= today]
    
    if active_or_upcoming:
        return min(active_or_upcoming, key=lambda x: x[0])
    
    return max(candidates, key=lambda x: x[1])

def keyword_prefilter_score(listing: JobListing) -> int:
    title = (listing.title or "").lower()
    description = (listing.description or "").lower()
    company = (listing.company or "").lower()
    location = (listing.location or "").lower()
    full_text = f"{title} {description} {company} {location}"

    seniority_hits = sum(term in title for term in config.SENIORITY_EXCLUSIONS) * 2
    seniority_hits += sum(term in description for term in config.SENIORITY_EXCLUSIONS)
    exp_info = _parse_experience(description)
    if seniority_hits >= 2 or not exp_info["eligible_for_rahul"]:
        return 0

    role_hits = _contains_any_word(title, config.ROLE_MATCH_TERMS)
    description_role_hits = _contains_any_word(description, config.ROLE_MATCH_TERMS)
    core_tech_hits = _contains_any(full_text, config.CORE_TECH_TERMS)
    
    if not role_hits and not description_role_hits:
        return 0

    location_points, location_hard_mismatch = _location_score(location)
    if location_hard_mismatch:
        return 0
    education_points, education_hard_mismatch = _education_score(f"{title} {description}")
    if education_hard_mismatch:
        return 0
    freshness_points, freshness_expired = _freshness_score(listing)
    if freshness_expired:
        return 0

    fresher_hits = _contains_any(full_text, config.FRESHER_SIGNALS)
    support_hits = _contains_any(full_text, config.PROFILE_KEYWORDS)
    infra_hits = _contains_any(full_text, getattr(config, "INFRASTRUCTURE_KEYWORDS", []))
    score = 0
    score += min(len(role_hits), 3) * 5
    score += min(len(description_role_hits), 3)
    score += min(len(core_tech_hits), 6) * 2
    # Cap infrastructure terms so they can't dominate the score
    score += min(len(support_hits), 8) + min(len(infra_hits), 2)
    score += min(len(fresher_hits), 2) * 4
    score += location_points
    score += education_points
    score += freshness_points

    # Walk-in Scoring & Deterministic Detection
    is_walkin = _contains_any(full_text, config.WALKIN_POSITIVE_SIGNALS)
    has_negative_walkin = _contains_any(full_text, config.WALKIN_NEGATIVE_SIGNALS)
    is_pune = _contains_any(full_text, config.PUNE_NEIGHBORHOODS)
    
    if is_walkin and not has_negative_walkin:
        # Check explicit dates in JD text early to reject expired walk-ins deterministically
        # Search for common date formats like 2024-03-24, 24th March, 24-03-2024
        # Since LLM is bypassed for rejection, we use standard regexes.
        start_date, end_date = _extract_walkin_date(description)
        if end_date:
            today = datetime.now(IST).date()
            if end_date < today:
                return 0
                
        # Require strong software engineering signal to grant the massive walk-in boost
        has_strong_role = len(role_hits) > 0 or (len(description_role_hits) > 0 and len(core_tech_hits) > 0)
        
        if has_strong_role:
            if getattr(config, "WALKIN_PRIORITY_ENABLED", True):
                score += 15
                if is_pune and getattr(config, "PUNE_WALKIN_PRIORITY", True):
                    score += 35  # Massive boost for Pune walk-ins
            
    if getattr(config, "FRESHER_ONLY_MODE", False) and not fresher_hits:
        return 0

    from utils.text import extract_email_from_text
    if extract_email_from_text(description):
        score += 1
    score -= seniority_hits
    return max(score, 0)


def prefilter(listings: list[JobListing]) -> list[JobListing]:
    scored = []
    for listing in listings:
        listing.prefilter_score = keyword_prefilter_score(listing)
        if listing.prefilter_score >= config.MIN_LIGHTWEIGHT_SCORE:
            scored.append(listing)

    by_source = {}
    for listing in scored:
        by_source.setdefault(listing.source, []).append(listing)
    for src in by_source:
        by_source[src].sort(key=lambda l: l.prefilter_score, reverse=True)

    final_pool = []
    min_slots = config.MIN_CANDIDATES_PER_SOURCE
    for src, src_listings in list(by_source.items()):
        final_pool.extend(src_listings[:min_slots])
        by_source[src] = src_listings[min_slots:]

    remaining_budget = max(0, config.MAX_LLM_CANDIDATES - len(final_pool))
    sources_with_candidates = {s: items for s, items in by_source.items() if items}
    while remaining_budget > 0 and sources_with_candidates:
        for src in list(sources_with_candidates.keys()):
            if remaining_budget <= 0:
                break
            final_pool.append(sources_with_candidates[src].pop(0))
            remaining_budget -= 1
            if not sources_with_candidates[src]:
                del sources_with_candidates[src]

    final_pool.sort(key=lambda l: l.prefilter_score, reverse=True)
    return final_pool[:config.MAX_LLM_CANDIDATES]


def _load_failed_ai_jobs() -> list[JobListing]:
    if not FAILED_AI_JOBS_PATH.exists():
        return []
    try:
        payload = json.loads(FAILED_AI_JOBS_PATH.read_text(encoding="utf-8"))
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
        if not isinstance(jobs, list):
            return []
        allowed = {field.name for field in fields(JobListing)}
        loaded = []
        seen = set()
        for item in jobs:
            if not isinstance(item, dict):
                continue
            data = {key: value for key, value in item.items() if key in allowed}
            url = str(data.get("job_url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            try:
                loaded.append(JobListing(**data))
            except TypeError:
                continue
        return loaded
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("Could not load failed-ai-jobs.json: %s", exc)
        return []


def _save_failed_ai_jobs(jobs: list[JobListing]) -> None:
    payload = {"version": 1, "updated_at": datetime.now(timezone.utc).isoformat(), "count": len(jobs), "jobs": [job.to_dict() for job in jobs]}
    FAILED_AI_JOBS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("run-artifacts").mkdir(parents=True, exist_ok=True)
    Path("run-artifacts/failed-ai-jobs.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("AI retry queue persisted: %s unresolved jobs", len(jobs))


def _load_ai_progress() -> dict:
    path = AI_PROGRESS_PATH
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") not in {2, 3}:
            return {}
        if payload.get("status") == "completed":
            return {}
        return payload
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("Could not load AI progress checkpoint: %s", exc)
        return {}


def _save_ai_progress(progress: dict) -> None:
    path = AI_PROGRESS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    progress["version"] = AI_PROGRESS_VERSION
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def _job_from_dict(data: dict) -> JobListing | None:
    if not isinstance(data, dict):
        return None
    allowed = {field.name for field in fields(JobListing)}
    filtered = {key: value for key, value in data.items() if key in allowed}
    try:
        return JobListing(**filtered)
    except (TypeError, ValueError):
        return None


def _apply_verdict(listing: JobListing, verdict: FitVerdict) -> bool:
    exp_info = _parse_experience(listing.description or "")
    if not exp_info["eligible_for_rahul"]:
        listing.fit_score = 0
        listing.fresher_appropriate = False
        listing.reason = exp_info["reason"]
        listing.fit_tier = "Reject"
        return False

    listing.role_match = max(0, min(getattr(verdict, "role_match", 0), 25))
    listing.experience_match = max(0, min(getattr(verdict, "experience_match", 0), 20))
    listing.technical_match = max(0, min(getattr(verdict, "technical_match", 0), 25))
    listing.project_match = max(0, min(getattr(verdict, "project_match", 0), 10))
    listing.education_match = max(0, min(getattr(verdict, "education_match", 0), 10))
    listing.location_match = max(0, min(getattr(verdict, "location_match", 0), 5))
    listing.company_quality = max(0, min(getattr(verdict, "company_quality", 0), 5))
    listing.fit_score = sum([listing.role_match, listing.experience_match, listing.technical_match, listing.project_match, listing.education_match, listing.location_match, listing.company_quality])
    listing.fresher_appropriate = getattr(verdict, "is_fresher_appropriate", False)
    listing.reason = getattr(verdict, "reason", "")
    
    # Walk-in fields
    listing.is_walkin = getattr(verdict, "is_walkin", False)
    raw_date = getattr(verdict, "walkin_date", "")
    listing.venue = getattr(verdict, "venue", "")
    
    # Deterministic Walk-in Validation
    if listing.is_walkin:
        listing.verification_status = "unknown"
        listing.walkin_date = ""
        start_date, end_date = _extract_walkin_date(listing.description or "")
        valid_date = None
        if raw_date and re.search(r"(\d{4}-\d{2}-\d{2})", raw_date):
            match = re.search(r"(\d{4}-\d{2}-\d{2})", raw_date)
            try:
                wd = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                if not start_date and not end_date:
                    valid_date = wd
                elif start_date and end_date and start_date <= wd <= end_date:
                    valid_date = wd
                elif start_date and wd == start_date:
                    valid_date = wd
                else:
                    valid_date = start_date
                    listing.walkin_date_conflict = True
            except ValueError:
                pass
        elif start_date:
            valid_date = start_date
            if raw_date and start_date.strftime("%Y-%m-%d") != raw_date:
                listing.walkin_date_conflict = True

        if valid_date:
            today = datetime.now(IST).date()
            listing.walkin_date = valid_date.strftime("%Y-%m-%d")
            effective_end = end_date if end_date else valid_date
            effective_start = start_date if start_date else valid_date
            
            if (today - effective_end).days > 0:
                listing.verification_status = "expired"
                listing.fit_score = 0
                listing.fresher_appropriate = False
                listing.reason = "Walk-in drive has expired."
                listing.fit_tier = "Reject"
                return False
            elif (today - effective_start).days >= 0 and (today - effective_end).days <= 0:
                listing.verification_status = "active"
            else:
                listing.verification_status = "upcoming"
    else:
        listing.walkin_date = ""
        listing.venue = ""
    
    if isinstance(getattr(verdict, "why", None), list):
        listing.reason = "; ".join(verdict.why)
    if isinstance(getattr(verdict, "gaps", None), list):
        listing.gaps = verdict.gaps

    if listing.fit_score >= 90:
        listing.fit_tier = "Exceptional"
    elif listing.fit_score >= 80:
        listing.fit_tier = "Strong"
    elif listing.fit_score >= 70:
        listing.fit_tier = "Good"
    elif listing.fit_score >= 60:
        listing.fit_tier = "Reasonable"
    else:
        listing.fit_tier = "Weak"
    return listing.fit_score >= config.LLM_FIT_THRESHOLD and listing.fresher_appropriate


def _deadline_reached(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _sleep_until(deadline: float | None, seconds: float) -> bool:
    if seconds <= 0:
        return not _deadline_reached(deadline)
    if deadline is None:
        time.sleep(seconds)
        return True
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    time.sleep(min(seconds, remaining))
    return not _deadline_reached(deadline)


def evaluate_listing(
    listing: JobListing,
    skip_gemini_retries: bool = False,
    deadline: float | None = None,
) -> tuple[FitVerdict | None, bool]:
    """Evaluate one candidate while respecting the shared AI deadline."""
    if _deadline_reached(deadline):
        return None, True

    prompt = _build_prompt(listing)
    delay = AI_RETRY_DELAY_SECONDS

    for attempt in range(1, AI_MAX_ATTEMPTS_PER_CANDIDATE + 1):
        if _deadline_reached(deadline):
            return None, True

        # 1. Try Groq first
        if not _groq_backoff.wait_if_needed(deadline):
            return None, True
        if _deadline_reached(deadline):
            return None, True
        groq_verdict = _groq.evaluate(prompt, skip_retries=attempt > 1)
        if not groq_verdict.hit_rate_limit and groq_verdict.reason != "evaluation failed":
            _groq_backoff.clear()
            return groq_verdict, False

        log.warning("Groq unavailable/rate-limited for '%s' on attempt %s; trying Gemini", listing.title, attempt)
        if groq_verdict.hit_rate_limit:
            _groq_backoff.activate(config.GROQ_SHARED_BACKOFF_SECONDS)

        # 2. Try Gemini
        if not _gemini_backoff.wait_if_needed(deadline):
            return None, True
        if _deadline_reached(deadline):
            return None, True
        gemini_verdict = _gemini.evaluate(prompt, skip_retries=skip_gemini_retries or attempt > 1)
        if not gemini_verdict.hit_rate_limit and gemini_verdict.reason != "evaluation failed":
            _gemini_backoff.clear()
            return gemini_verdict, False

        log.warning("Gemini unavailable/rate-limited for '%s' on attempt %s; trying AI Gateway", listing.title, attempt)
        if gemini_verdict.hit_rate_limit:
            _gemini_backoff.activate(config.GEMINI_SHARED_BACKOFF_SECONDS)
        
        # 3. Try Gateway
        if not _gateway_backoff.wait_if_needed(deadline):
            return None, True
        if _deadline_reached(deadline):
            return None, True
        gateway_verdict = _gateway.evaluate(prompt)
        if gateway_verdict is not None:
            _gateway_backoff.clear()
            return gateway_verdict, False

        # If we got here, Gateway failed as well. Activate its backoff.
        _gateway_backoff.activate(config.AI_GATEWAY_SHARED_BACKOFF_SECONDS)

        reason = "all AI providers failed"
        
        log.warning("%s for '%s' on attempt %s/%s", reason, listing.title, attempt, AI_MAX_ATTEMPTS_PER_CANDIDATE)
        if attempt < AI_MAX_ATTEMPTS_PER_CANDIDATE and not _sleep_until(deadline, min(AI_MAX_RETRY_DELAY_SECONDS, delay)):
            return None, True
        delay = min(AI_MAX_RETRY_DELAY_SECONDS, max(1.0, delay * 2))

    return None, True


def _legacy_state_store():
    """Build the unified store and import legacy files only when necessary."""
    store = AIStateStore()
    if store.load():
        return store

    progress = _load_ai_progress()
    retry_payload: dict = {}
    if FAILED_AI_JOBS_PATH.exists():
        try:
            raw = json.loads(FAILED_AI_JOBS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                retry_payload = raw
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            retry_payload = {}

    migrated = migrate_legacy_progress(progress) + migrate_legacy_retry_jobs(
        retry_payload.get("jobs", []) if isinstance(retry_payload, dict) else []
    )
    if migrated:
        deduped: dict[str, EvaluationState] = {}
        for state in migrated:
            existing = deduped.get(state.job_url)
            if existing is None or state.status in {RETRYABLE_ERROR, DEADLINE_EXCEEDED}:
                deduped[state.job_url] = state
        store.replace_all(deduped.values())
    return store


def review_candidates(listings: list[JobListing], deadline: float | None = None) -> list[JobListing]:
    """Review jobs with one authoritative per-job state machine."""
    if deadline is None:
        budget_seconds = max(1, int(getattr(config, "LLM_EVALUATION_BUDGET_SECONDS", 2700)))
        deadline = time.monotonic() + budget_seconds

    store = _legacy_state_store()
    states = store.load()
    retry_jobs = []
    retry_urls = set()
    for job in listings:
        state = states.get(job.job_url)
        if state and state.status in {RETRYABLE_ERROR, DEADLINE_EXCEEDED, EVALUATING, QUEUED}:
            retry_jobs.append(job)
            retry_urls.add(job.job_url)

    progress = _load_ai_progress()
    profile_text = _profile()
    profile_digest = profile_hash(profile_text)
    candidate_urls = [job.job_url for job in listings if job.job_url]
    progress_identity = checkpoint_identity(candidate_urls[:config.MAX_LLM_CANDIDATES], profile_digest)

    if progress and not compatible(progress, candidate_urls[:config.MAX_LLM_CANDIDATES], profile_digest):
        log.warning("Ignoring incompatible legacy AI checkpoint; unified state is authoritative")
        progress = {}

    resumed_jobs = []
    for job in listings:
        state = states.get(job.job_url)
        expected_key = evaluation_key(job.job_url, job.description, profile_digest)
        if state and state.status in {PASSED, REJECTED, EVALUATED} and state.evaluation_key == expected_key and state.verdict:
            verdict = FitVerdict(**{k: v for k, v in state.verdict.items() if k in {"fit_score", "is_fresher_appropriate", "reason", "hit_rate_limit", "role_match", "experience_match", "technical_match", "project_match", "education_match", "location_match", "company_quality", "decision", "why", "gaps"}})
            _apply_verdict(job, verdict)
            resumed_jobs.append(job)

    resumed_urls = {job.job_url for job in resumed_jobs}
    new_jobs = [job for job in listings if job.job_url and job.job_url not in resumed_urls and job.job_url not in retry_urls]
    ordered_jobs = retry_jobs + new_jobs[:config.MAX_LLM_CANDIDATES]

    passed = [job for job in resumed_jobs if job.fit_score >= config.LLM_FIT_THRESHOLD and job.fresher_appropriate]
    coordinator = MetricsCoordinator(AI_PROGRESS_PATH, metrics_enabled=getattr(config, "AI_METRICS_ENABLED", True))
    coordinator.save_progress({
        **(progress or {}),
        **progress_identity,
        "version": AI_PROGRESS_VERSION,
        "status": "in_progress",
        "candidate_urls": [job.job_url for job in ordered_jobs],
        "evaluated_count": len(resumed_jobs),
        "total_candidates": len(ordered_jobs) + len(resumed_jobs),
    })

    def worker(listing: JobListing) -> tuple[JobListing, FitVerdict | None, bool, float]:
        state = states.get(listing.job_url) or EvaluationState(job_url=listing.job_url)
        state.start_attempt()
        state.evaluation_key = evaluation_key(listing.job_url, listing.description, profile_digest)
        store.upsert(state)
        started = time.monotonic()
        coordinator.record_candidate_start()
        if _deadline_reached(deadline):
            state.transition(DEADLINE_EXCEEDED, error="ai_deadline_exceeded", evaluation_key=state.evaluation_key)
            store.upsert(state)
            return listing, None, True, time.monotonic() - started
        verdict, unresolved = evaluate_listing(listing, deadline=deadline)
        if unresolved:
            state.transition(RETRYABLE_ERROR if not _deadline_reached(deadline) else DEADLINE_EXCEEDED, error="provider_or_deadline_failure", evaluation_key=state.evaluation_key)
        else:
            state.transition(EVALUATED, evaluation_key=state.evaluation_key, verdict=verdict.__dict__ if verdict else None)
        store.upsert(state)
        return listing, verdict, unresolved, time.monotonic() - started

    with ThreadPoolExecutor(max_workers=config.AI_MAX_CONCURRENCY, thread_name_prefix="ai-review") as executor:
        futures = {executor.submit(worker, listing): listing for listing in ordered_jobs}
        for future in as_completed(futures):
            listing = futures[future]
            try:
                listing, verdict, unresolved, duration = future.result()
            except Exception as exc:
                log.exception("AI worker crashed for '%s': %s", listing.title, exc)
                state = states.get(listing.job_url) or EvaluationState(job_url=listing.job_url)
                state.transition(RETRYABLE_ERROR, error=str(exc), evaluation_key=evaluation_key(listing.job_url, listing.description, profile_digest))
                store.upsert(state)
                verdict, unresolved, duration = None, True, 0.0

            if unresolved or verdict is None:
                coordinator.record_candidate_result(status="UNRESOLVED", duration_seconds=duration)
            else:
                passed_flag = _apply_verdict(listing, verdict)
                final_state = store.get(listing.job_url) or EvaluationState(job_url=listing.job_url)
                final_state.transition(PASSED if passed_flag else REJECTED, evaluation_key=evaluation_key(listing.job_url, listing.description, profile_digest), verdict=verdict.__dict__)
                store.upsert(final_state)
                coordinator.record_candidate_result(status="PASSED" if passed_flag else "REJECTED", duration_seconds=duration)
                if passed_flag:
                    passed.append(listing)

    deadline_reached = _deadline_reached(deadline)
    progress = {
        **progress_identity,
        "version": AI_PROGRESS_VERSION,
        "status": "deadline_exceeded" if deadline_reached else "completed",
        "evaluated_count": sum(1 for state in store.load().values() if state.status in {EVALUATED, PASSED, REJECTED}),
        "total_candidates": len(ordered_jobs) + len(resumed_jobs),
        "state_store": "run-artifacts/ai-state.json",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    coordinator.save_progress(progress)
    try:
        Path("run-artifacts").mkdir(parents=True, exist_ok=True)
        summary = {**coordinator.snapshot(), "candidate_count": len(ordered_jobs) + len(resumed_jobs), "status": progress["status"]}
        Path("run-artifacts/ai-metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        Path("run-artifacts/ai-evaluation-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("Could not write AI metrics artifact: %s", exc)

    # Legacy retry artifact is retained as a compatibility/export view only;
    # correctness comes from ai-state.json.
    retry_export = []
    for state in store.load().values():
        if state.status in {RETRYABLE_ERROR, DEADLINE_EXCEEDED, EVALUATING, QUEUED}:
            job = next((item for item in listings if item.job_url == state.job_url), None)
            if job:
                retry_export.append(job)
    _save_failed_ai_jobs(retry_export)
    passed.sort(key=lambda l: l.fit_score, reverse=True)
    return passed
