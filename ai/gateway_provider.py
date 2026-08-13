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

                # Retry only transient upstream/server failures. Client-side
                # errors and quota/auth failures should fail fast to Gemini.
                if 400 <= resp.status_code < 500:
                    log.warning(
                        "gateway rejected request with HTTP %s; falling back to Gemini",
                        resp.status_code,
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
                return FitVerdict(
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
            except requests.RequestException as exc:
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
                log.warning("gateway response invalid: %s — falling back to Gemini", exc)
                return None

        return None
