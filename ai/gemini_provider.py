"""Fallback AI provider — Gemini free tier. Called only when the primary
AI gateway fails. Retries on 429 with backoff UNLESS skip_retries is set
(see evaluator.py's adaptive quota detection: once a run confirms Gemini's
daily quota is exhausted even as a fallback, retrying is pointless)."""
import json
import requests

import config
from models import FitVerdict
from ai.base import AIProvider
from utils.logging_setup import get_logger

log = get_logger("gemini")


class GeminiProvider(AIProvider):
    name = "Gemini"

    def evaluate(self, prompt: str, skip_retries: bool = False) -> FitVerdict:
        max_retries = 0 if skip_retries else 3
        backoff_seconds = 15

        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(
                    config.GEMINI_URL,
                    headers={"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"},
                    json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                          "generationConfig": {"temperature": 0, "maxOutputTokens": 200}},
                    timeout=30,
                )
                if resp.status_code == 429:
                    if attempt < max_retries:
                        wait = int(resp.headers.get("Retry-After", backoff_seconds * (attempt + 1)))
                        log.warning(f"rate limited — retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                        import time; time.sleep(wait)
                        continue
                    return FitVerdict(hit_rate_limit=True, reason="rate limited")

                resp.raise_for_status()
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                parsed = json.loads(text)
                return FitVerdict(
                    fit_score=parsed.get("fit_score", 0),
                    is_fresher_appropriate=parsed.get("is_fresher_appropriate", False),
                    reason=parsed.get("reason", ""),
                    hit_rate_limit=False,
                )
            except Exception as exc:
                log.warning(f"evaluation failed: {exc}")
                return FitVerdict(reason="evaluation failed", hit_rate_limit=False)

        return FitVerdict(reason="evaluation failed", hit_rate_limit=False)
