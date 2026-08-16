"""Build the candidate context used in every AI fit-evaluation prompt.

Defaults to the condensed profile (skills/projects/education/CP summary)
instead of the full canonical master JSON — the full dump was the main
driver of slow, timeout-prone Gemini/gateway calls (see
ai/profile_condensed.py for the full rationale). Set AI_PROFILE_MODE=full
as an env var / in config.py to go back to the full profile for a run.
"""
import config
from ai.profile_adapter import get_full_profile_text
from ai.profile_condensed import build_condensed_profile


def build_candidate_profile() -> str:
    mode = str(getattr(config, "AI_PROFILE_MODE", "condensed")).lower()
    if mode == "full":
        return get_full_profile_text()
    return build_condensed_profile()
