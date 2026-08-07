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
    return f"""Here is a candidate's background:

{_profile()}

Here is a job listing:
Title: {listing.title}
Company: {listing.company}
Description: {listing.description[:3000]}

Judge whether this specific listing is a genuinely good fit for this candidate
— a fresher/final-year student — not just whether the tech stack overlaps.
Reject roles that need real professional experience even if titled "SDE 1" or
similar, and reject unpaid internships. Respond with ONLY a JSON object, no
other text, in this exact shape:
{{"fit_score": <0-100 integer>, "is_fresher_appropriate": <true/false>, "reason": "<one sentence>"}}"""


def keyword_prefilter_score(listing: JobListing) -> int:
    title = listing.title.lower()
    description = listing.description.lower()
    full_text = f"{title} {description} {listing.company.lower()}"

    seniority_hits = sum(term in title for term in config.SENIORITY_EXCLUSIONS) * 2
    seniority_hits += sum(term in description for term in config.SENIORITY_EXCLUSIONS)
    if seniority_hits >= 2:
        return 0

    score = sum(sig in full_text for sig in config.FRESHER_SIGNALS) * 4
    score += sum(kw in full_text for kw in config.PROFILE_KEYWORDS)
    if any(comp in full_text for comp in config.PRIORITY_COMPANIES):
        score += 3
    # Directly-published contact email is more actionable for cold-email
    # outreach — boosted so it survives the cut to review more reliably.
    from utils.text import extract_email_from_text
    if extract_email_from_text(listing.description):
        score += 4
    score -= seniority_hits
    return max(score, 0)


def prefilter(listings: list[JobListing], min_score: int = 3) -> list[JobListing]:
    scored = []
    for listing in listings:
        listing.prefilter_score = keyword_prefilter_score(listing)
        if listing.prefilter_score >= min_score:
            scored.append(listing)
    scored.sort(key=lambda l: l.prefilter_score, reverse=True)
    return scored[:config.MAX_LLM_CANDIDATES]


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

        listing.fit_score = verdict.fit_score
        listing.fresher_appropriate = verdict.is_fresher_appropriate
        listing.reason = verdict.reason

        if verdict.reason == "all LLM providers failed — not evaluated":
            consecutive_failures += 1
        else:
            consecutive_failures = 0

        if consecutive_failures >= config.CONSECUTIVE_RATE_LIMIT_BREAKER:
            log.warning(f"{config.CONSECUTIVE_RATE_LIMIT_BREAKER} candidates in a row failed on BOTH the gateway and Gemini — "
                        f"stopping here rather than burning the run's time budget. Remaining candidates picked up next run.")
            break

        if verdict.fit_score >= config.LLM_FIT_THRESHOLD and verdict.is_fresher_appropriate:
            passed.append(listing)

        # No blanket pacing needed here anymore — that 4.5s delay was
        # specifically calibrated for Gemini's free-tier RPM limit back
        # when it was called for every single candidate. Now the gateway
        # (not rate-limited the same way) is primary, so Gemini is only
        # called occasionally as fallback — pace only those calls.
        if gemini_hit_rate_limit and not gemini_confirmed_exhausted:
            time.sleep(4.5)

    passed.sort(key=lambda l: l.fit_score, reverse=True)
    return passed
