"""Fallback AI provider — self-hosted multi-provider gateway
(github.com/rahulxgit/ai-gateway), used ONLY when Gemini's retries are
exhausted. The gateway already fails over across 7+ providers internally,
so one call here is effectively backed by multiple providers already —
no retry loop needed on this side. No auth required (open endpoint)."""
import json
import requests

import config
from models import FitVerdict
from ai.base import AIProvider
from utils.logging_setup import get_logger

log = get_logger("gateway")


class GatewayProvider(AIProvider):
    name = "AI Gateway"

    def evaluate(self, prompt: str) -> FitVerdict:
        try:
            resp = requests.post(
                f"{config.AI_GATEWAY_URL}/chat",
                headers={"Content-Type": "application/json"},
                json={"messages": [{"role": "user", "content": prompt}], "taskType": "reasoning"},
                timeout=45,
            )
            resp.raise_for_status()
            content = resp.json().get("content", "")
            text = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(text)
            return FitVerdict(
                fit_score=parsed.get("fit_score", 0),
                is_fresher_appropriate=parsed.get("is_fresher_appropriate", False),
                reason=parsed.get("reason", ""),
            )
        except Exception as exc:
            log.warning(f"gateway fallback failed: {exc}")
            return None  # distinguishes "gateway also failed" from "gateway said no" for the caller
