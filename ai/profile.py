"""Build the candidate context exclusively from the canonical master profile."""
from ai.profile_adapter import get_full_profile_text


def build_candidate_profile() -> str:
    return get_full_profile_text()
