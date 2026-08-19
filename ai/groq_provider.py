"""Groq provider for lightning-fast Llama 3 evaluations."""
import time
import requests

import config
from models import FitVerdict
from ai.base import AIProvider
from ai.provider_state import record_failure, record_request, record_success
from utils.llm_json import as_bool, as_int, as_str_list, parse_json_object
from utils.logging_setup import get_logger

log = get_logger("groq")

class GroqProvider(AIProvider):
    name = "Groq"

    def evaluate(self, prompt: str, skip_retries: bool = False) -> FitVerdict:
        max_retries = 0 if skip_retries else config.GROQ_MAX_RETRIES
        backoff_seconds = config.GROQ_MAX_RETRY_WAIT_SECONDS

        if not config.GROQ_API_KEY:
            return FitVerdict(reason="evaluation failed", hit_rate_limit=False)

        for attempt in range(max_retries + 1):
            started = time.monotonic()
            record_request(self.name)
            try:
                resp = requests.post(
                    config.GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {config.GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": config.GROQ_MODEL,
                        "messages": [
                            {"role": "system", "content": "You evaluate software engineering job descriptions based strictly on the user's criteria. Output ONLY a valid JSON object matching the requested schema. No conversational text."},
                            {"role": "user", "content": prompt}
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.0,
                        "max_tokens": config.GROQ_MAX_OUTPUT_TOKENS,
                    },
                    timeout=config.GROQ_TIMEOUT_SECONDS,
                )

                if resp.status_code == 429:
                    latency = time.monotonic() - started
                    retry_after_raw = resp.headers.get("Retry-After", "")
                    try:
                        retry_after = float(retry_after_raw)
                    except (TypeError, ValueError):
                        retry_after = backoff_seconds * (attempt + 1)

                    wait = min(max(retry_after, 0), config.GROQ_MAX_RETRY_WAIT_SECONDS)
                    if attempt < max_retries and wait > 0:
                        record_failure(self.name, "RATE_LIMITED", latency, cooldown_seconds=wait)
                        log.warning("rate limited - retrying in %ss (attempt %s/%s)", wait, attempt + 1, max_retries)
                        time.sleep(wait)
                        continue
                    record_failure(self.name, "RATE_LIMITED", latency)
                    return FitVerdict(hit_rate_limit=True, reason="rate limited")

                if 400 <= resp.status_code < 500:
                    latency = time.monotonic() - started
                    record_failure(self.name, f"HTTP_{resp.status_code}", latency)
                    log.warning("Groq rejected request with HTTP %s: %s", resp.status_code, resp.text)
                    return FitVerdict(reason="evaluation failed", hit_rate_limit=False)

                resp.raise_for_status()
                payload = resp.json()
                text = payload["choices"][0]["message"]["content"]
                parsed = parse_json_object(text)
                why = as_str_list(parsed.get("why"))
                gaps = as_str_list(parsed.get("gaps"))
                reason = str(parsed.get("reason") or "").strip() or "; ".join(why)
                verdict = FitVerdict(
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
                record_success(self.name, time.monotonic() - started)
                return verdict
            except requests.Timeout as exc:
                latency = time.monotonic() - started
                record_failure(self.name, "TIMEOUT", latency)
                log.warning("Groq timeout (attempt %s/%s): %s", attempt + 1, max_retries + 1, exc)
                if attempt == max_retries:
                    return FitVerdict(reason="evaluation failed", hit_rate_limit=False)
            except requests.RequestException as exc:
                latency = time.monotonic() - started
                record_failure(self.name, "NETWORK_ERROR", latency)
                log.warning("evaluation failed (attempt %s/%s): %s", attempt + 1, max_retries + 1, exc)
                if attempt == max_retries:
                    return FitVerdict(reason="evaluation failed", hit_rate_limit=False)
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                record_failure(self.name, "INVALID_RESPONSE", time.monotonic() - started)
                log.warning("evaluation failed (attempt %s/%s): %s", attempt + 1, max_retries + 1, exc)
                if attempt == max_retries:
                    return FitVerdict(reason="evaluation failed", hit_rate_limit=False)

        return FitVerdict(reason="evaluation failed", hit_rate_limit=False)
