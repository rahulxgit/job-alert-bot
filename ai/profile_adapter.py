"""Canonical career-profile loader for job matching and application context.

Only ``data/rahul-master-profile.json`` is read. Private contact fields and
secrets are excluded from model context while the full factual career context
is preserved, even when the master profile uses schema aliases or nesting.
"""
from __future__ import annotations

import json
from typing import Any

import config
from utils.logging_setup import get_logger

log = get_logger("profile_adapter")
MASTER_PROFILE_PATH = config.PROFILE_DATA_PATH


class ProfileLoadError(Exception):
    """Raised when the canonical master profile cannot be loaded."""


def load_canonical_profile() -> dict[str, Any]:
    try:
        with open(MASTER_PROFILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        log.error("Failed to load canonical profile from %s: %s", MASTER_PROFILE_PATH, exc)
        raise ProfileLoadError(f"Failed to load master profile: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise ProfileLoadError("Canonical master profile is empty or invalid.")
    return data


_PRIVATE_OR_SECRET_KEYS = {
    "phone", "pin_code", "full_address", "password", "passwords", "api_key", "api_keys",
    "token", "tokens", "cookie", "cookies", "authentication_secrets", "secrets",
    "refresh_token", "access_token", "client_secret", "private_key", "resume_pdf",
}


def _sanitize_for_matching(value: Any, key: str = "") -> Any:
    key_lower = key.lower()
    if key_lower in _PRIVATE_OR_SECRET_KEYS or any(secret in key_lower for secret in ("password", "api_key", "token", "cookie", "secret")):
        return None
    if isinstance(value, dict):
        cleaned = {}
        for child_key, child_value in value.items():
            sanitized = _sanitize_for_matching(child_value, child_key)
            if sanitized is not None:
                cleaned[child_key] = sanitized
        return cleaned
    if isinstance(value, list):
        return [item for item in (_sanitize_for_matching(item, key) for item in value) if item is not None]
    return value


def _normalize_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def _find_alias_value(data: dict[str, Any], aliases: set[str]) -> Any:
    normalized_aliases = {_normalize_key(alias) for alias in aliases}

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            for key, value in node.items():
                if _normalize_key(str(key)) in normalized_aliases and value not in (None, "", [], {}):
                    return value
            for value in node.values():
                found = walk(value)
                if found not in (None, "", [], {}):
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found not in (None, "", [], {}):
                    return found
        return None

    return walk(data)


def _section(title: str, value: Any) -> list[str]:
    if value in (None, "", [], {}):
        value = "No dedicated section was found; consult Additional Master-Profile Data only when relevant."
    return [f"\n## {title}\n{json.dumps(value, ensure_ascii=False, indent=2)}"]


def get_full_profile_text() -> str:
    data = build_structured_profile()
    section_specs = [
        ("Identity & Career Stage", {"identity", "career_stage", "personal_identity"}),
        ("Contact & Public Profiles", {"contact", "public_profiles"}),
        ("Location & Work Preferences", {"location", "work_preferences", "preferred_locations"}),
        ("Professional Profile", {"professional_profile", "professional_summary", "professional_identity"}),
        ("Career Objective", {"career_objective", "career_goals", "objective"}),
        ("Education", {"education", "academic_background", "academics"}),
        ("Experience", {"experience", "work_experience", "internships", "employment"}),
        ("Skills", {"skills", "technical_skills", "technical_profile", "technical_stack", "skillset", "technologies"}),
        ("AI Engineering", {"ai_engineering", "ai_capabilities", "ai_skills", "llm_engineering"}),
        ("Projects", {"projects", "project_portfolio", "project_experience"}),
        ("Leadership", {"leadership", "leadership_experience", "campus_leadership"}),
        ("Achievements", {"achievements", "awards", "honors"}),
        ("Competitive Programming / CP Profile", {"competitive_programming", "competitive_programming_profile", "cp_profile", "programming_profile", "coding_profile", "ds_algorithm_profile"}),
        ("Job Preferences", {"job_preferences", "career_preferences", "target_preferences"}),
        ("Application / Career Content", {"application_content", "application_profile", "application_context", "resume_context"}),
        ("Cover Letter / Motivation Context", {"cover_letter", "cover_letter_context", "motivation", "motivation_context"}),
        ("Interview / Personal Positioning", {"about_narrative", "personal_brand", "interview_context", "positioning", "personal_positioning"}),
    ]

    selected = [(title, _find_alias_value(data, aliases)) for title, aliases in section_specs]
    remaining = {
        key: value for key, value in data.items()
        if key not in {"_meta", "privacy", "identity", "contact", "location", "professional_profile", "career_objective", "education", "experience", "projects", "leadership", "achievements", "job_preferences", "about_narrative"}
    }
    selected.append(("Additional Master-Profile Data", remaining))

    lines = [
        "CANONICAL CANDIDATE PROFILE — SOURCE OF TRUTH",
        "Use this profile as the factual authority for matching. Do not invent missing facts.",
    ]
    for title, value in selected:
        lines.extend(_section(title, value))
    return "\n".join(lines)


def build_structured_profile() -> dict[str, Any]:
    data = _sanitize_for_matching(load_canonical_profile())
    assert isinstance(data, dict)
    return data


def get_profile_text() -> str:
    return get_full_profile_text()
