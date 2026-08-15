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
from ai.provider_state import record_failure, record_request, record_success
from utils.llm_json import as_bool, as_int, as_str_list, parse_json_object
from utils.logging_setup import get_logger

log = get_logger("gateway")


class GatewayProvider(AIProvider):
    name = "AI Gateway"

    def evaluate(self, prompt: str, max_retries: int | None = None) -> FitVerdict | None:
        """Return a normalized verdict, or None so the caller can use Gemini.

        Gateway failures are deliberately classified as recoverable provider
        failures. The timeout/retry budget is kept short so a degraded gateway
        cannot consume the entire daily job-search window.
        """
        retries = config.AI_GATEWAY_MAX_RETRIES if max_retries is None else max(0, max_retries)

        for attempt in range(retries + 1):
            started = time.monotonic()
            record_request(self.name)
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
                if isinstance(status_code, int) and status_code == 429:
                    latency = time.monotonic() - started
                    record_failure(self.name, "RATE_LIMITED", latency)
                    log.warning("gateway rate limited; falling back to Gemini")
                    return None

                if isinstance(status_code, int) and 400 <= status_code < 500:
                    latency = time.monotonic() - started
                    record_failure(self.name, f"HTTP_{status_code}", latency)
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
                record_success(self.name, time.monotonic() - started)
                return verdict
            except requests.Timeout as exc:
                latency = time.monotonic() - started
                record_failure(self.name, "TIMEOUT", latency)
                if attempt < retries:
                    log.warning(
                        "gateway timeout (attempt %s/%s): %s — retrying in %.1fs",
                        attempt + 1,
                        retries + 1,
                        exc,
                        config.AI_GATEWAY_RETRY_DELAY_SECONDS,
                    )
                    time.sleep(config.AI_GATEWAY_RETRY_DELAY_SECONDS)
                    continue
                log.warning(
                    "gateway unavailable after %s attempts: %s — falling back to Gemini",
                    retries + 1,
                    exc,
                )
                return None
            except requests.RequestException as exc:
                latency = time.monotonic() - started
                status = "HTTP_5XX" if "5" in str(getattr(getattr(exc, "response", None), "status_code", "")) else "NETWORK_ERROR"
                record_failure(self.name, status, latency)
                if attempt < retries:
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
                    retries + 1,
                    exc,
                )
                return None
            except (ValueError, TypeError, KeyError) as exc:
                record_failure(self.name, "INVALID_RESPONSE", time.monotonic() - started)
                log.warning("gateway response invalid: %s — falling back to Gemini", exc)
                return None

        return None
