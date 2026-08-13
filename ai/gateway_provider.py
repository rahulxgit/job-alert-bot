"""
Primary AI provider — self-hosted multi-provider gateway
(github.com/rahulxgit/ai-gateway, deployed at ai-gateway-wx35.onrender.com).
Called first for every candidate. The gateway already fails over across
multiple providers internally, so transient failures should fall back to
Gemini rather than aborting the run.
"""
import time

import requests

import config
from models import FitVerdict
from ai.base import AIProvider
from utils.llm_json import as_bool, as_int, as_str_list, parse_json_object
from utils.logging_setup import get_logger

log = get_logger("gateway")

# Provider-wide circuit breaker. Repeated gateway failures are usually a
# gateway health problem, not a candidate-specific problem. Stopping further
# calls prevents the evaluator's per-candidate retry loop from multiplying a
# provider outage across hundreds of jobs.
_GATEWAY_FAILURE_BREAKER = max(1, int(getattr(config, "AI_GATEWAY_FAILURE_BREAKER", 3)))
_gateway_consecutive_failures = 0
_gateway_open = False


def _record_success() -> None:
    global _gateway_consecutive_failures, _gateway_open
    _gateway_consecutive_failures = 0
    _gateway_open = False


def _record_failure(reason: str) -> None:
    global _gateway_consecutive_failures, _gateway_open
    _gateway_consecutive_failures += 1
    if _gateway_consecutive_failures >= _GATEWAY_FAILURE_BREAKER:
        _gateway_open = True
        log.error(
            "AI Gateway circuit opened after %s consecutive failures: %s",
            _gateway_consecutive_failures,
            reason,
        )


def gateway_circuit_open() -> bool:
    return _gateway_open


class GatewayProvider(AIProvider):
    name = "AI Gateway"

    def evaluate(self, prompt: str, max_retries: int | None = None) -> FitVerdict | None:
        """Return a normalized verdict, or None so the caller can use Gemini.

        Gateway failures are deliberately classified as recoverable provider
        failures. The timeout/retry budget is kept short so a degraded gateway
        cannot consume the entire daily job-search window.
        """
        if _gateway_open:
            log.warning("AI Gateway circuit is open; skipping gateway request")
            return None

        retries = config.AI_GATEWAY_MAX_RETRIES if max_retries is None else max(0, max_retries)

        for attempt in range(retries + 1):
            try:
                resp = requests.post(
                    f"{config.AI_GATEWAY_URL}/chat",
                    headers={"Content-Type": "application/json"},
                    json={
                        "messages": [{"role": "user", "content": prompt}],
                        "taskType": "reasoning",
                    },
                    timeout=config.AI_GATEWAY_TIMEOUT_SECONDS,
                )

                status_code = getattr(resp, "status_code", None)
                if isinstance(status_code, int) and 400 <= status_code < 500:
                    _record_failure(f"HTTP {status_code}")
                    log.warning(
                        "gateway rejected request with HTTP %s; falling back to Gemini",
                        status_code,
                    )
                    return None

                resp.raise_for_status()

                payload = resp.json()
                if not isinstance(payload, dict):
                    raise ValueError("gateway response root was not an object")

                content = payload.get("content", "")
                if isinstance(content, dict):
                    parsed = content
                elif isinstance(content, str) and content.strip():
                    parsed = parse_json_object(content)
                else:
                    raise ValueError("gateway response contained empty content")

                why = as_str_list(parsed.get("why"))
                gaps = as_str_list(parsed.get("gaps"))
                reason = str(parsed.get("reason") or "").strip() or "; ".join(why)
                verdict = FitVerdict(
                    fit_score=as_int(parsed.get("fit_score")),
                    is_fresher_appropriate=as_bool(parsed.get("is_fresher_appropriate")),
                    reason=reason,
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
                _record_success()
                return verdict
            except requests.RequestException as exc:
                _record_failure(str(exc))
                if attempt < retries and not _gateway_open:
                    log.warning(
                        "gateway transient failure (attempt %s/%s): %s — retrying in %.1fs",
                        attempt + 1,
                        retries + 1,
                        exc,
                        config.AI_GATEWAY_RETRY_DELAY_SECONDS,
                    )
                    time.sleep(config.AI_GATEWAY_RETRY_DELAY_SECONDS)
                    continue
                log.warning(
                    "gateway unavailable after %s attempts: %s — falling back to Gemini",
                    attempt + 1,
                    exc,
                )
                return None
            except (ValueError, TypeError, KeyError) as exc:
                _record_failure(str(exc))
                log.warning("gateway response invalid: %s — falling back to Gemini", exc)
                return None

        return None
