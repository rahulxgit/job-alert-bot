"""
Orchestrates the full matching pipeline: cheap keyword pre-filter -> Gemini
review (with adaptive quota detection) -> AI gateway fallback -> circuit
breaker. This is the module that ties ai/base.py's providers together.
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
    """Returns (verdict, hit_rate_limit_bool)."""
    prompt = _build_prompt(listing)
    verdict = _gemini.evaluate(prompt, skip_retries=skip_gemini_retries)

    if verdict.hit_rate_limit:
        if skip_gemini_retries:
            log.info(f"Gemini still exhausted for '{listing.title}' — going straight to AI gateway")
        else:
            log.warning(f"'{listing.title}' rate-limited after retries — falling back to AI gateway")
        fallback = _gateway.evaluate(prompt)
        if fallback is not None:
            return fallback, True
        from models import FitVerdict
        return FitVerdict(reason="all LLM providers failed — not evaluated"), True

    if verdict.reason == "evaluation failed":
        fallback = _gateway.evaluate(prompt)
        if fallback is not None:
            return fallback, False
        from models import FitVerdict
        return FitVerdict(reason="all LLM providers failed — not evaluated"), False

    return verdict, False


def review_candidates(listings: list[JobListing]) -> list[JobListing]:
    """Runs the full Gemini/gateway review with adaptive quota detection
    and the rate-limit circuit breaker. Mutates and returns only listings
    that pass LLM_FIT_THRESHOLD."""
    passed = []
    consecutive_failures = 0
    gemini_confirmed_exhausted = False

    for listing in listings:
        verdict, hit_rate_limit = evaluate_listing(listing, skip_gemini_retries=gemini_confirmed_exhausted)

        if hit_rate_limit and not gemini_confirmed_exhausted:
            gemini_confirmed_exhausted = True
            log.info("Gemini's quota confirmed exhausted for this run — skipping retry waits on all remaining candidates")

        listing.fit_score = verdict.fit_score
        listing.fresher_appropriate = verdict.is_fresher_appropriate
        listing.reason = verdict.reason

        if verdict.reason == "all LLM providers failed — not evaluated":
            consecutive_failures += 1
        else:
            consecutive_failures = 0

        if consecutive_failures >= config.CONSECUTIVE_RATE_LIMIT_BREAKER:
            log.warning(f"{config.CONSECUTIVE_RATE_LIMIT_BREAKER} candidates in a row failed on BOTH Gemini and the gateway — "
                        f"stopping here rather than burning the run's time budget. Remaining candidates picked up next run.")
            break

        if verdict.fit_score >= config.LLM_FIT_THRESHOLD and verdict.is_fresher_appropriate:
            passed.append(listing)

        if not gemini_confirmed_exhausted:
            time.sleep(4.5)  # free-tier Gemini pacing (~15 req/min)

    passed.sort(key=lambda l: l.fit_score, reverse=True)
    return passed
