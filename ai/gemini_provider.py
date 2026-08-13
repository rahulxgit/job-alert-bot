"""Fallback AI provider — Gemini free tier.

Uses Gemini's structured JSON output mode plus defensive parsing. Retry
budget is deliberately short so provider quota/errors cannot consume the
entire daily job-search window.
"""
import time

import requests

import config
from models import FitVerdict
from ai.base import AIProvider
from utils.llm_json import as_bool, as_int, as_str_list, parse_json_object
from utils.logging_setup import get_logger

log = get_logger("gemini")

# Gemini quota/rate-limit state is run-local. Once the service explicitly
# reports exhausted quota, retrying every remaining candidate is wasteful and
# increases latency without improving coverage.
_gemini_quota_exhausted = False
_gemini_consecutive_failures = 0
_GEMINI_FAILURE_BREAKER = max(1, int(getattr(config, "GEMINI_FAILURE_BREAKER", 3)))


def gemini_quota_exhausted() -> bool:
    return _gemini_quota_exhausted


def _record_success() -> None:
    global _gemini_consecutive_failures
    _gemini_consecutive_failures = 0


def _record_failure() -> None:
    global _gemini_consecutive_failures
    _gemini_consecutive_failures += 1


class GeminiProvider(AIProvider):
    name = "Gemini"

    def evaluate(self, prompt: str, skip_retries: bool = False) -> FitVerdict:
        global _gemini_quota_exhausted

        if _gemini_quota_exhausted:
            log.warning("Gemini circuit is open because quota/rate limit was exhausted")
            return FitVerdict(hit_rate_limit=True, reason="rate limited")

        max_retries = 0 if skip_retries else config.GEMINI_MAX_RETRIES
        backoff_seconds = config.GEMINI_MAX_RETRY_WAIT_SECONDS

        response_schema = {
            "type": "OBJECT",
            "properties": {
                "fit_score": {"type": "INTEGER"},
                "role_match": {"type": "INTEGER"},
                "experience_match": {"type": "INTEGER"},
                "technical_match": {"type": "INTEGER"},
                "project_match": {"type": "INTEGER"},
                "education_match": {"type": "INTEGER"},
                "location_match": {"type": "INTEGER"},
                "company_quality": {"type": "INTEGER"},
                "decision": {"type": "STRING"},
                "is_fresher_appropriate": {"type": "BOOLEAN"},
                "why": {"type": "ARRAY", "items": {"type": "STRING"}},
                "gaps": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": [
                "fit_score", "role_match", "experience_match", "technical_match",
                "project_match", "education_match", "location_match", "company_quality",
                "decision", "is_fresher_appropriate", "why", "gaps",
            ],
        }

        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(
                    config.GEMINI_URL,
                    headers={
                        "x-goog-api-key": config.GEMINI_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json={
                        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": 0,
                            "maxOutputTokens": 512,
                            "responseMimeType": "application/json",
                            "responseSchema": response_schema,
                        },
                    },
                    timeout=config.GEMINI_TIMEOUT_SECONDS,
                )

                if resp.status_code == 429:
                    _record_failure()
                    retry_after_raw = resp.headers.get("Retry-After", "")
                    try:
                        retry_after = int(retry_after_raw)
                    except (TypeError, ValueError):
                        retry_after = backoff_seconds * (attempt + 1)

                    wait = min(max(retry_after, 0), config.GEMINI_MAX_RETRY_WAIT_SECONDS)
                    if attempt < max_retries and wait > 0:
                        log.warning(
                            "rate limited — retrying in %ss (attempt %s/%s)",
                            wait,
                            attempt + 1,
                            max_retries,
                        )
                        time.sleep(wait)
                        continue
                    _gemini_quota_exhausted = True
                    log.error("Gemini quota/rate limit exhausted; disabling Gemini for the rest of this run")
                    return FitVerdict(hit_rate_limit=True, reason="rate limited")

                if 400 <= resp.status_code < 500:
                    _record_failure()
                    log.warning("Gemini rejected request with HTTP %s", resp.status_code)
                    if _gemini_consecutive_failures >= _GEMINI_FAILURE_BREAKER:
                        _gemini_quota_exhausted = True
                        log.error("Gemini circuit opened after repeated client/provider failures")
                    return FitVerdict(reason="evaluation failed", hit_rate_limit=False)

                resp.raise_for_status()
                payload = resp.json()
                text = payload["candidates"][0]["content"]["parts"][0]["text"]
                parsed = parse_json_object(text)
                why = as_str_list(parsed.get("why"))
                gaps = as_str_list(parsed.get("gaps"))
                reason = str(parsed.get("reason") or "").strip() or "; ".join(why)
                _record_success()
                return FitVerdict(
                    fit_score=as_int(parsed.get("fit_score")),
                    is_fresher_appropriate=as_bool(parsed.get("is_fresher_appropriate")),
                    reason=reason,
                    hit_rate_limit=False,
                    role_match=as_int(parsed.get("role_match")),
                    experience_match=as_int(parsed.get("experience_match")),
                    technical_match=as_int(parsed.get("technical_match")),
                    project_match=as_int(parsed.get("project_match")),
                    education_match=as_int(parsed.get("education_match")),
                    location_match=as_int(parsed.get("location_match")),
                    company_quality=as_int(parsed.get("company_quality")),
                    decision=str(parsed.get("decision") or ""),
                    why=why,
                    gaps=gaps,
                )
            except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as exc:
                _record_failure()
                log.warning("evaluation failed (attempt %s/%s): %s", attempt + 1, max_retries + 1, exc)
                if attempt == max_retries:
                    if _gemini_consecutive_failures >= _GEMINI_FAILURE_BREAKER:
                        _gemini_quota_exhausted = True
                    return FitVerdict(reason="evaluation failed", hit_rate_limit=False)

        return FitVerdict(reason="evaluation failed", hit_rate_limit=False)
