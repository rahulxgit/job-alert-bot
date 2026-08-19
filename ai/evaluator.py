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
_gateway = GatewayProvider()
_candidate_profile = None
FAILED_AI_JOBS_PATH = Path("failed-ai-jobs.json")
AI_PROGRESS_PATH = Path("run-artifacts/ai-progress.json")
AI_PROGRESS_VERSION = CHECKPOINT_VERSION
AI_MAX_ATTEMPTS_PER_CANDIDATE = max(1, int(getattr(config, "AI_EVALUATION_MAX_ATTEMPTS_PER_CANDIDATE", 3)))
AI_RETRY_DELAY_SECONDS = max(1.0, float(getattr(config, "AI_EVALUATION_RETRY_DELAY_SECONDS", 15)))
AI_MAX_RETRY_DELAY_SECONDS = max(AI_RETRY_DELAY_SECONDS, float(getattr(config, "AI_EVALUATION_MAX_RETRY_DELAY_SECONDS", 60)))
_gemini_backoff = ProviderBackoff()
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
- For education fit, check degree/branch, graduation timing, CGPA constraints, and stated eligibility; do not assume a branch is accepted when the JD explicitly excludes it.
- For experience fit, distinguish internship/production project evidence from full-time professional experience.
- Leadership, achievements, and CP data can improve fit when relevant but cannot override hard eligibility failures.
- Location fit must use the profile's actual preferences; do not invent relocation willingness.
- Company/industry preferences are a modest factor, not a standalone rejection reason.
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
  "gaps": ["specific gap or uncertainty"]
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
    
    if not role_hits and len(core_tech_hits) < 1:
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

        if not _gemini_backoff.wait_if_needed(deadline):
            return None, True
        if _deadline_reached(deadline):
            return None, True
        gemini_verdict = _gemini.evaluate(prompt, skip_retries=skip_gemini_retries or attempt > 1)
        if not gemini_verdict.hit_rate_limit and gemini_verdict.reason != "evaluation failed":
            _gemini_backoff.clear()
            return gemini_verdict, False

        log.warning("Gemini unavailable/rate-limited for '%s' on attempt %s; trying AI Gateway", listing.title, attempt)
        
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

        reason = "Gemini rate limited" if gemini_verdict.hit_rate_limit else "both AI providers failed"
        if gemini_verdict.hit_rate_limit:
            _gemini_backoff.activate(config.GEMINI_SHARED_BACKOFF_SECONDS)
        
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
