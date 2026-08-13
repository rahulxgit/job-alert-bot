"""Canonical career-profile loader for job matching and application context.

Only ``data/rahul-master-profile.json`` is read. Private contact fields and
secrets are excluded from model context while the full factual career context
is preserved. Stable compatibility sections are derived from the canonical
profile so existing callers/tests do not depend on one exact JSON layout.
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


def _find_alias_values(data: dict[str, Any], aliases: set[str]) -> list[Any]:
    """Collect all matching alias values without duplicating identical objects."""
    normalized_aliases = {_normalize_key(alias) for alias in aliases}
    found: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if _normalize_key(str(key)) in normalized_aliases and value not in (None, "", [], {}):
                    if value not in found:
                        found.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found


def _stable_section_values(data: dict[str, Any], title: str) -> Any:
    """Return a useful stable section even when facts live under nested schema keys."""
    aliases: dict[str, set[str]] = {
        "Identity & Career Stage": {"identity", "career_stage", "personal_identity"},
        "Contact & Public Profiles": {"contact", "public_profiles", "profiles"},
        "Location & Work Preferences": {"location", "work_preferences", "preferred_locations"},
        "Professional Profile": {"professional_profile", "professional_summary", "professional_identity"},
        "Career Objective": {"career_objective", "career_goals", "objective"},
        "Education": {"education", "academic_background", "academics"},
        "Experience": {"experience", "work_experience", "internships", "employment"},
        "Skills": {"skills", "technical_skills", "technical_profile", "technical_stack", "skillset", "technologies", "tech_stack"},
        "AI Engineering": {"ai_engineering", "ai_capabilities", "ai_skills", "llm_engineering", "verified_ai_engineering"},
        "Projects": {"projects", "project_portfolio", "project_experience", "flagship_projects", "ai_projects", "professional_projects"},
        "Leadership": {"leadership", "leadership_experience", "campus_leadership", "activities"},
        "Achievements": {"achievements", "awards", "honors", "recognition"},
        "Competitive Programming / CP Profile": {"competitive_programming", "competitive_programming_profile", "cp_profile", "programming_profile", "coding_profile", "ds_algorithm_profile", "competitive_programming_data"},
        "Job Preferences": {"job_preferences", "career_preferences", "target_preferences"},
        "Application / Career Content": {"application_content", "application_profile", "application_context", "resume_context"},
        "Cover Letter / Motivation Context": {"cover_letter", "cover_letter_context", "motivation", "motivation_context"},
        "Interview / Personal Positioning": {"about_narrative", "personal_brand", "interview_context", "positioning", "personal_positioning"},
    }
    values = _find_alias_values(data, aliases[title])
    if not values:
        return "No dedicated section was found; consult Additional Master-Profile Data only when relevant."
    if len(values) == 1:
        return values[0]
    return values


def _section(title: str, value: Any) -> list[str]:
    return [f"\n## {title}\n{json.dumps(value, ensure_ascii=False, indent=2)}"]


def get_full_profile_text(data: dict[str, Any] | None = None) -> str:
    """Serialize the canonical profile into complete model context."""
    if data is None:
        data = _sanitize_for_matching(load_canonical_profile())
    assert isinstance(data, dict)

    section_titles = [
        "Identity & Career Stage", "Contact & Public Profiles", "Location & Work Preferences",
        "Professional Profile", "Career Objective", "Education", "Experience", "Skills",
        "AI Engineering", "Projects", "Leadership", "Achievements", "Competitive Programming / CP Profile",
        "Job Preferences", "Application / Career Content", "Cover Letter / Motivation Context",
        "Interview / Personal Positioning",
    ]

    lines = [
        "CANONICAL CANDIDATE PROFILE — SOURCE OF TRUTH",
        "Use this profile as the factual authority for matching. Do not invent missing facts.",
    ]
    for title in section_titles:
        lines.extend(_section(title, _stable_section_values(data, title)))

    # Preserve all remaining canonical data rather than silently dropping a future field.
    remaining = {
        key: value for key, value in data.items()
        if key not in {"_meta", "privacy"}
    }
    lines.extend(_section("Complete Canonical Profile Snapshot", remaining))
    return "\n".join(lines)


def build_structured_profile() -> dict[str, Any]:
    """Return sanitized structured evidence plus the legacy raw_text contract."""
    data = _sanitize_for_matching(load_canonical_profile())
    assert isinstance(data, dict)

    # Preserve the historically expected top-level compatibility shape while
    # keeping the master profile as the sole source of facts.
    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    education = data.get("education") if isinstance(data.get("education"), list) else []
    experience = data.get("experience") if isinstance(data.get("experience"), list) else []
    data["identity"] = {
        **identity,
        "career_stage": identity.get("career_stage", "entry-level"),
        "name": identity.get("full_name", ""),
    }
    data["education"] = education
    data["experience"] = experience
    data["raw_text"] = get_full_profile_text(data)
    return data


def get_profile_text() -> str:
    return get_full_profile_text()
