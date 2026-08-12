import re
"""
Orchestrates the full matching pipeline: cheap keyword pre-filter -> AI
gateway review (primary) -> Gemini fallback (with adaptive quota
detection) -> circuit breaker. This is the module that ties
ai/base.py's providers together.
"""
import time
import config
from models import JobListing
from ai.gemini_provider import GeminiProvider
from ai.gateway_provider import GatewayProvider
from ai.profile import build_candidate_profile
from utils.logging_setup import get_logger

log = get_logger("evaluator")

_gemini = GeminiProvider()
_gateway = GatewayProvider()
_candidate_profile = None  # lazy-loaded, cached


def _profile() -> str:
    global _candidate_profile
    if _candidate_profile is None:
        _candidate_profile = build_candidate_profile()
    return _candidate_profile


def _build_prompt(listing: JobListing) -> str:
    from ai.profile_adapter import get_profile_text
    profile_text = get_profile_text()
    return f"""Here is a candidate's background:

{profile_text}

Here is a job listing:
Title: {listing.title}
Company: {listing.company}
Description: {listing.description[:3000]}

Candidate experience eligibility:
- Rahul is a 2026 graduate / entry-level candidate.
- Freshers and new graduates are eligible.
- 0 years, 0-1 years, 0-2 years and up to 1 year required experience are eligible.
- Mandatory required experience above 1 year is not eligible.
- 2+ years required must be rejected.
- 3+ years required must be rejected.
- Senior/Lead/Staff/Principal/Manager roles must be rejected.
- Preferred experience above 1 year is not automatically a rejection if fresh graduates are explicitly accepted.

Evaluate if this job is a strong match for this specific candidate.
Consider role alignment, experience required, tech alignment, project relevance, education eligibility, and location.

Respond with ONLY a JSON object, no other text, in this exact shape:
{{
  "fit_score": <0-100 integer>,
  "role_match": <0-25 integer>,
  "experience_match": <0-20 integer>,
  "technical_match": <0-25 integer>,
  "project_match": <0-10 integer>,
  "education_match": <0-10 integer>,
  "location_match": <0-5 integer>,
  "company_quality": <0-5 integer>,
  "decision": "<strong_match|good_match|weak_match|reject>",
  "is_fresher_appropriate": <true/false>,
  "why": ["<reason 1>", "<reason 2>"],
  "gaps": ["<gap 1>", "<gap 2>"]
}}"""

def _parse_experience(text: str) -> dict:
    """
    Detects experience requirements.
    Returns dict with min_years, max_years, required, preferred, graduate_friendly, eligible_for_rahul, reason.
    """
    text_lower = text.lower()

    res = {
        "min_years": 0,
        "max_years": 0,
        "required": False,
        "preferred": False,
        "graduate_friendly": False,
        "eligible_for_rahul": True,
        "reason": ""
    }

    # Check graduate signals
    graduate_signals = ["new grad", "fresher", "0-1 years", "0-1 yrs", "0-1 yr", "0 to 1", "0-2 years", "0-2 yrs", "0-2 yr", "0 to 2", "0 - 2", "0 – 2", "0–1", "0–2", "up to 1 year", "1 year experience", "1+ years", "final-year", "2026 graduate", "graduate", "entry level", "entry-level"]
    if any(sig in text_lower for sig in graduate_signals):
        res["graduate_friendly"] = True

    # Check strict requirements > 1 year
    req_match = re.search(r"\b([2-9]|1[0-9])\+?\s*(?:\+|to|-|–|\s)*\s*(?:years?|yrs?)\s*(?:of\s*experience)?\b", text_lower)
    if req_match:
        years = int(req_match.group(1))
        # Check if it's preferred
        if re.search(r"\b([2-9]|1[0-9])\+?\s*(?:\+|to|-|–|\s)*\s*(?:years?|yrs?).{0,20}(?:preferred|a plus|nice to have|advantage|bonus)\b", text_lower):
            res["preferred"] = True
            res["min_years"] = years
        elif "required" in text_lower or "minimum" in text_lower or "must have" in text_lower or re.search(r"\b([2-9]|1[0-9])\+?\s*(?:\+|to|-|–|\s)*\s*(?:years?|yrs?)\b", text_lower):
            res["required"] = True
            res["min_years"] = years

            # If mandatory > 1 year AND not graduate friendly -> Reject
            if years > 1 and not res["graduate_friendly"]:
                res["eligible_for_rahul"] = False
                res["reason"] = f"Mandatory experience ({years}+ years) exceeds 1 year and no fresher signal found."

    # Also hard reject explicit senior titles unless it's a false positive
    seniority_hits = sum(term in text_lower for term in config.SENIORITY_EXCLUSIONS)
    if seniority_hits >= 2 and not res["graduate_friendly"]:
        res["eligible_for_rahul"] = False
        res["reason"] = "Role appears too senior based on title/description keywords."

    return res

def keyword_prefilter_score(listing: JobListing) -> int:
    title = listing.title.lower()
    description = listing.description.lower()
    full_text = f"{title} {description} {listing.company.lower()}"

    seniority_hits = sum(term in title for term in config.SENIORITY_EXCLUSIONS) * 2
    seniority_hits += sum(term in description for term in config.SENIORITY_EXCLUSIONS)

    exp_info = _parse_experience(description)
    if seniority_hits >= 2 or not exp_info["eligible_for_rahul"]:
        return 0

    score = sum(sig in full_text for sig in config.FRESHER_SIGNALS) * 4
    score += sum(kw in full_text for kw in config.PROFILE_KEYWORDS)
    if any(comp in full_text for comp in config.PRIORITY_COMPANIES):
        score += 3

    from utils.text import extract_email_from_text
    if extract_email_from_text(listing.description):
        score += 4
    score -= seniority_hits
    return max(score, 0)


def prefilter(listings: list[JobListing]) -> list[JobListing]:
    scored = []
    for listing in listings:
        listing.prefilter_score = keyword_prefilter_score(listing)
        if listing.prefilter_score >= config.MIN_LIGHTWEIGHT_SCORE:
            scored.append(listing)

    # Group by source to ensure one massive source doesn't drown out others
    by_source = {}
    for listing in scored:
        by_source.setdefault(listing.source, []).append(listing)

    final_pool = []

    # Sort each source's candidates by score
    for src in by_source:
        by_source[src].sort(key=lambda l: l.prefilter_score, reverse=True)

    # Phase 1: Minimum guaranteed review slots per source
    MIN_SLOTS = getattr(config, 'MIN_CANDIDATES_PER_SOURCE', 5)
    for src, src_listings in list(by_source.items()):
        taken = src_listings[:MIN_SLOTS]
        final_pool.extend(taken)
        by_source[src] = src_listings[MIN_SLOTS:]

    # Phase 2: Fair allocation of remaining capacity among sources that still have candidates
    remaining_budget = max(0, config.MAX_LLM_CANDIDATES - len(final_pool))

    sources_with_candidates = {s: items for s, items in by_source.items() if items}

    while remaining_budget > 0 and sources_with_candidates:
        # Allocate 1 slot per source round-robin to ensure fairness
        for src in list(sources_with_candidates.keys()):
            if remaining_budget <= 0:
                break

            src_listings = sources_with_candidates[src]
            final_pool.append(src_listings.pop(0))
            remaining_budget -= 1

            if not src_listings:
                del sources_with_candidates[src]

    final_pool.sort(key=lambda l: l.prefilter_score, reverse=True)
    return final_pool



def evaluate_listing(listing: JobListing, skip_gemini_retries: bool = False) -> tuple:
    """Returns (verdict, gemini_hit_rate_limit_bool). Gateway is primary —
    tried first for every candidate. Gemini is the fallback, only called
    when the gateway itself fails (not just says no — a real failure)."""
    prompt = _build_prompt(listing)
    verdict = _gateway.evaluate(prompt)

    if verdict is not None:
        return verdict, False

    # Gateway failed outright — fall back to Gemini
    log.warning(f"gateway failed for '{listing.title}' — falling back to Gemini")
    gemini_verdict = _gemini.evaluate(prompt, skip_retries=skip_gemini_retries)

    if gemini_verdict.hit_rate_limit:
        if skip_gemini_retries:
            log.info(f"Gemini (fallback) still exhausted for '{listing.title}'")
        return gemini_verdict, True

    if gemini_verdict.reason == "evaluation failed":
        from models import FitVerdict
        return FitVerdict(reason="all LLM providers failed — not evaluated"), False

    return gemini_verdict, False


def review_candidates(listings: list[JobListing]) -> list[JobListing]:
    """Runs the full gateway/Gemini review with adaptive quota detection
    (for when Gemini is hit repeatedly as fallback) and the rate-limit
    circuit breaker. Mutates and returns only listings that pass
    LLM_FIT_THRESHOLD."""
    passed = []
    consecutive_failures = 0
    gemini_confirmed_exhausted = False

    for listing in listings:
        verdict, gemini_hit_rate_limit = evaluate_listing(listing, skip_gemini_retries=gemini_confirmed_exhausted)

        if gemini_hit_rate_limit and not gemini_confirmed_exhausted:
            gemini_confirmed_exhausted = True
            log.info("Gemini (fallback) quota confirmed exhausted for this run — skipping its retry waits for the rest of the run")

        # Deterministic Eligibility Check
        exp_info = _parse_experience(listing.description)
        if not exp_info["eligible_for_rahul"]:
            listing.fit_score = 0
            listing.fresher_appropriate = False
            listing.reason = exp_info["reason"]
            listing.fit_tier = "Reject"
            continue

        listing.role_match = max(0, min(getattr(verdict, 'role_match', 0), 25))
        listing.experience_match = max(0, min(getattr(verdict, 'experience_match', 0), 20))
        listing.technical_match = max(0, min(getattr(verdict, 'technical_match', 0), 25))
        listing.project_match = max(0, min(getattr(verdict, 'project_match', 0), 10))
        listing.education_match = max(0, min(getattr(verdict, 'education_match', 0), 10))
        listing.location_match = max(0, min(getattr(verdict, 'location_match', 0), 5))
        listing.company_quality = max(0, min(getattr(verdict, 'company_quality', 0), 5))

        # Calculate fit score deterministically
        calculated_fit_score = (
            listing.role_match
            + listing.experience_match
            + listing.technical_match
            + listing.project_match
            + listing.education_match
            + listing.location_match
            + listing.company_quality
        )

        listing.fit_score = calculated_fit_score
        listing.fresher_appropriate = getattr(verdict, 'is_fresher_appropriate', False)
        listing.reason = getattr(verdict, 'reason', "")

        # Combine 'why' array into reason if it's a list, same with gaps
        if hasattr(verdict, 'why') and isinstance(verdict.why, list):
            listing.reason = "; ".join(verdict.why)
        if hasattr(verdict, 'gaps') and isinstance(verdict.gaps, list):
            listing.gaps = verdict.gaps

        # Tier logic based on deterministic score
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

        if getattr(verdict, 'reason', "") == "all LLM providers failed — not evaluated":
            consecutive_failures += 1
        else:
            consecutive_failures = 0

        if consecutive_failures >= config.CONSECUTIVE_RATE_LIMIT_BREAKER:
            log.warning(f"{config.CONSECUTIVE_RATE_LIMIT_BREAKER} candidates in a row failed on BOTH the gateway and Gemini — "
                        f"stopping here rather than burning the run's time budget. Remaining candidates picked up next run.")
            break

        if listing.fit_score >= config.LLM_FIT_THRESHOLD and listing.fresher_appropriate and exp_info["eligible_for_rahul"]:
            passed.append(listing)

        if gemini_hit_rate_limit and not gemini_confirmed_exhausted:
            time.sleep(4.5)

    passed.sort(key=lambda l: l.fit_score, reverse=True)
    return passed
