import re
"""Job-fit evaluation driven by the canonical master profile."""
import time
from datetime import datetime, timezone

import config
from models import FitVerdict, JobListing
from ai.gemini_provider import GeminiProvider
from ai.gateway_provider import GatewayProvider
from ai.profile import build_candidate_profile
from utils.logging_setup import get_logger

log = get_logger("evaluator")
_gemini = GeminiProvider()
_gateway = GatewayProvider()
_candidate_profile = None


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
- For education fit, check degree/branch, graduation timing, CGPA constraints, and stated eligibility; do not assume a branch is accepted when the JD explicitly excludes it.
- For experience fit, distinguish internship/production project evidence from full-time professional experience.
- Leadership, achievements, and CP data can improve fit when relevant but cannot override hard eligibility failures.
- Location fit must use the profile's actual preferences; do not invent relocation willingness.
- Company/industry preferences are a modest factor, not a standalone rejection reason.
- Application/cover-letter/motivation context can support alignment only when those facts exist in the profile.
- If a material requirement cannot be verified, say so in gaps instead of assuming it.
- Reasons and gaps must mention specific candidate/JD evidence.

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

DECISION
========
strong_match = strong alignment with no material hard blocker
good_match = solid alignment with manageable gaps
weak_match = partial alignment with material gaps/uncertainty
reject = hard eligibility blocker, seniority mismatch, or very poor alignment

OUTPUT
======
Return ONLY valid JSON. No markdown fences or surrounding prose.
All numeric fields are integers. why and gaps are arrays of strings.

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
  "gaps": ["specific gap or uncertainty"]
}}
"""


def _parse_experience(text: str) -> dict:
    text_lower = text.lower()
    res = {
        "min_years": 0,
        "max_years": 0,
        "required": False,
        "preferred": False,
        "graduate_friendly": False,
        "eligible_for_rahul": True,
        "reason": "",
    }
    graduate_signals = [
        "new grad", "fresher", "0-1 years", "0-1 yrs", "0-1 yr", "0 to 1",
        "0-2 years", "0-2 yrs", "0-2 yr", "0 to 2", "0 - 2", "0 – 2", "0–1",
        "0–2", "up to 1 year", "1 year experience", "1+ years", "final-year",
        "2026 graduate", "graduate", "entry level", "entry-level",
    ]
    if any(sig in text_lower for sig in graduate_signals):
        res["graduate_friendly"] = True

    req_match = re.search(
        r"\b([2-9]|1[0-9])\+?\s*(?:\+|to|-|–|\s)*\s*(?:years?|yrs?)\s*(?:of\s*experience)?\b",
        text_lower,
    )
    if req_match:
        years = int(req_match.group(1))
        res["min_years"] = years
        preferred_match = re.search(
            r"\b([2-9]|1[0-9])\+?\s*(?:\+|to|-|–|\s)*\s*(?:years?|yrs?).{0,30}"
            r"(?:preferred|a plus|nice to have|advantage|bonus)\b",
            text_lower,
        )
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


def _contains_any(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term in text]


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
    if _contains_any(normalized, config.EDUCATION_HARD_EXCLUSION_SIGNALS):
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
        posted = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0, False
    age_days = (datetime.now(timezone.utc) - posted).days
    if age_days < 0:
        return 1, False
    if age_days <= 3:
        return 4, False
    if age_days <= 7:
        return 2, False
    if age_days <= config.FRESHNESS_DAYS:
        return 0, False
    return -3, True


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

    role_hits = _contains_any(title, config.ROLE_MATCH_TERMS)
    description_role_hits = _contains_any(description, config.ROLE_MATCH_TERMS)
    core_tech_hits = _contains_any(full_text, config.CORE_TECH_TERMS)

    # A broad keyword hit is not enough. A candidate must show a plausible
    # target role, or multiple directly relevant technologies, before AI.
    if not role_hits and len(core_tech_hits) < 2:
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

    score = 0
    score += min(len(role_hits), 3) * 5
    score += min(len(description_role_hits), 3)
    score += min(len(core_tech_hits), 6) * 2
    score += min(len(support_hits), 8)
    score += min(len(fresher_hits), 2) * 4
    score += location_points
    score += education_points
    score += freshness_points

    if any(comp in full_text for comp in config.PRIORITY_COMPANIES):
        score += 3

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

    final_pool = []
    for src in by_source:
        by_source[src].sort(key=lambda l: l.prefilter_score, reverse=True)

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
            src_listings = sources_with_candidates[src]
            final_pool.append(src_listings.pop(0))
            remaining_budget -= 1
            if not src_listings:
                del sources_with_candidates[src]

    final_pool.sort(key=lambda l: l.prefilter_score, reverse=True)
    return final_pool[: config.MAX_LLM_CANDIDATES]


def evaluate_listing(listing: JobListing, skip_gemini_retries: bool = False) -> tuple:
    prompt = _build_prompt(listing)
    verdict = _gateway.evaluate(prompt)
    if verdict is not None:
        return verdict, False
    log.warning("gateway failed for '%s' — falling back to Gemini", listing.title)
    gemini_verdict = _gemini.evaluate(prompt, skip_retries=skip_gemini_retries)
    if gemini_verdict.hit_rate_limit:
        return gemini_verdict, True
    if gemini_verdict.reason == "evaluation failed":
        return FitVerdict(reason="all LLM providers failed — not evaluated"), False
    return gemini_verdict, False


def review_candidates(listings: list[JobListing], deadline: float | None = None) -> list[JobListing]:
    """Review up to the configured candidate pool.

    ``deadline`` is retained for backward compatibility with the earlier Phase 1
    call path, but the short 20-minute cutoff is intentionally disabled so it
    cannot reduce job coverage. The GitHub Actions job timeout remains the final
    external safety boundary until runtime optimization is addressed separately.
    """
    _ = deadline
    passed = []
    consecutive_failures = 0
    gemini_confirmed_exhausted = False
    for listing in listings[: config.MAX_LLM_CANDIDATES]:
        verdict, gemini_hit_rate_limit = evaluate_listing(
            listing,
            skip_gemini_retries=gemini_confirmed_exhausted,
        )
        if gemini_hit_rate_limit and not gemini_confirmed_exhausted:
            gemini_confirmed_exhausted = True
            log.info("Gemini quota confirmed exhausted for this run — skipping retry waits thereafter")

        exp_info = _parse_experience(listing.description or "")
        if not exp_info["eligible_for_rahul"]:
            listing.fit_score = 0
            listing.fresher_appropriate = False
            listing.reason = exp_info["reason"]
            listing.fit_tier = "Reject"
            continue

        listing.role_match = max(0, min(getattr(verdict, "role_match", 0), 25))
        listing.experience_match = max(0, min(getattr(verdict, "experience_match", 0), 20))
        listing.technical_match = max(0, min(getattr(verdict, "technical_match", 0), 25))
        listing.project_match = max(0, min(getattr(verdict, "project_match", 0), 10))
        listing.education_match = max(0, min(getattr(verdict, "education_match", 0), 10))
        listing.location_match = max(0, min(getattr(verdict, "location_match", 0), 5))
        listing.company_quality = max(0, min(getattr(verdict, "company_quality", 0), 5))
        listing.fit_score = sum([
            listing.role_match,
            listing.experience_match,
            listing.technical_match,
            listing.project_match,
            listing.education_match,
            listing.location_match,
            listing.company_quality,
        ])
        listing.fresher_appropriate = getattr(verdict, "is_fresher_appropriate", False)
        listing.reason = getattr(verdict, "reason", "")
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

        if getattr(verdict, "reason", "") == "all LLM providers failed — not evaluated":
            consecutive_failures += 1
        else:
            consecutive_failures = 0

        if consecutive_failures >= config.CONSECUTIVE_RATE_LIMIT_BREAKER:
            log.warning(
                "%s consecutive LLM failures — stopping to protect the run budget",
                config.CONSECUTIVE_RATE_LIMIT_BREAKER,
            )
            break

        if listing.fit_score >= config.LLM_FIT_THRESHOLD and listing.fresher_appropriate:
            passed.append(listing)

        if gemini_hit_rate_limit and not gemini_confirmed_exhausted:
            time.sleep(4.5)

    passed.sort(key=lambda l: l.fit_score, reverse=True)
    return passed
