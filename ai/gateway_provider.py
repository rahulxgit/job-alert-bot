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

    def evaluate(self, prompt: str, max_retries: int = 1) -> FitVerdict | None:
        """Return a normalized verdict, or None so the caller can use Gemini."""
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(
                    f"{config.AI_GATEWAY_URL}/chat",
                    headers={"Content-Type": "application/json"},
                    json={
                        "messages": [{"role": "user", "content": prompt}],
                        "taskType": "reasoning",
                    },
                    timeout=45,
                )
                resp.raise_for_status()

                payload = resp.json()
                content = payload.get("content", "") if isinstance(payload, dict) else ""
                if isinstance(content, dict):
                    parsed = content
                else:
                    parsed = parse_json_object(str(content))

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
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                if attempt < max_retries:
                    log.warning(
                        "gateway call failed (attempt %s/%s): %s — retrying in 3s",
                        attempt + 1,
                        max_retries + 1,
                        exc,
                    )
                    time.sleep(3)
                else:
                    log.warning(
                        "gateway failed after %s attempts: %s — falling back to Gemini",
                        max_retries + 1,
                        exc,
                    )
        return None
