"""Fallback AI provider — Gemini free tier.

Uses Gemini's structured JSON output mode plus defensive parsing. Retries
429s when useful, but malformed provider output is treated as a failed
candidate evaluation rather than a fatal workflow error.
"""
import time
import requests

import config
from models import FitVerdict
from ai.base import AIProvider
from utils.llm_json import as_bool, as_int, as_str_list, parse_json_object
from utils.logging_setup import get_logger

log = get_logger("gemini")


class GeminiProvider(AIProvider):
    name = "Gemini"

    def evaluate(self, prompt: str, skip_retries: bool = False) -> FitVerdict:
        max_retries = 0 if skip_retries else 3
        backoff_seconds = 15

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
                    timeout=30,
                )
                if resp.status_code == 429:
                    if attempt < max_retries:
                        wait = int(resp.headers.get("Retry-After", backoff_seconds * (attempt + 1)))
                        log.warning(
                            "rate limited — retrying in %ss (attempt %s/%s)",
                            wait,
                            attempt + 1,
                            max_retries,
                        )
                        time.sleep(wait)
                        continue
                    return FitVerdict(hit_rate_limit=True, reason="rate limited")

                resp.raise_for_status()
                payload = resp.json()
                text = payload["candidates"][0]["content"]["parts"][0]["text"]
                parsed = parse_json_object(text)
                why = as_str_list(parsed.get("why"))
                gaps = as_str_list(parsed.get("gaps"))
                reason = str(parsed.get("reason") or "").strip() or "; ".join(why)
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
                log.warning("evaluation failed (attempt %s/%s): %s", attempt + 1, max_retries + 1, exc)
                if attempt == max_retries:
                    return FitVerdict(reason="evaluation failed", hit_rate_limit=False)

        return FitVerdict(reason="evaluation failed", hit_rate_limit=False)
