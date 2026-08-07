"""
Primary AI provider — self-hosted multi-provider gateway
(github.com/rahulxgit/ai-gateway, deployed at ai-gateway-wx35.onrender.com).
Called first for every candidate. The gateway already fails over across
7+ providers internally, so a single call here is effectively backed by
multiple providers already. Given a light retry (2 attempts) since it's
now the primary path and deserves more resilience than a one-shot
fallback call — a transient network blip shouldn't immediately punt to
Gemini. No auth required (open endpoint).
"""
import json
import time
import requests

import config
from models import FitVerdict
from ai.base import AIProvider
from utils.logging_setup import get_logger

log = get_logger("gateway")


class GatewayProvider(AIProvider):
    name = "AI Gateway"

    def evaluate(self, prompt: str, max_retries: int = 1) -> FitVerdict:
        """Returns a FitVerdict, or None if every attempt failed —
        None specifically signals the caller to fall back to Gemini."""
        for attempt in range(max_retries + 1):
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
                if attempt < max_retries:
                    log.warning(f"gateway call failed (attempt {attempt + 1}/{max_retries + 1}): {exc} — retrying in 3s")
                    time.sleep(3)
                else:
                    log.warning(f"gateway failed after {max_retries + 1} attempts: {exc} — falling back to Gemini")
        return None
