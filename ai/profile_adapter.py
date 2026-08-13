"""Canonical career-profile loader for job matching and application context.

Only ``data/rahul-master-profile.json`` is read. The adapter deliberately
excludes private contact fields and secrets while preserving the full factual
career context needed for high-quality JD matching.
"""
from __future__ import annotations

import json
import os
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
    """Recursively remove private/secrets and internal source-control noise."""
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


def build_structured_profile() -> dict[str, Any]:
    """Return the complete sanitized canonical profile as structured evidence."""
    data = load_canonical_profile()
    sanitized = _sanitize_for_matching(data)
    assert isinstance(sanitized, dict)
    return sanitized


def _section(title: str, value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    body = json.dumps(value, ensure_ascii=False, indent=2)
    return [f"\n## {title}\n{body}"]


def get_full_profile_text() -> str:
    """Serialize the canonical profile into complete, readable model context."""
    data = build_structured_profile()
    preferred_sections = [
        ("Identity & Career Stage", data.get("identity")),
        ("Contact & Public Profiles", data.get("contact")),
        ("Location & Work Preferences", data.get("location")),
        ("Professional Profile", data.get("professional_profile")),
        ("Career Objective", data.get("career_objective")),
        ("Education", data.get("education")),
        ("Experience", data.get("experience")),
        ("Skills", data.get("skills")),
        ("AI Engineering", data.get("ai_engineering")),
        ("Projects", data.get("projects")),
        ("Leadership", data.get("leadership")),
        ("Achievements", data.get("achievements")),
        ("Competitive Programming / CP Profile", data.get("competitive_programming")),
        ("Job Preferences", data.get("job_preferences")),
        ("Application / Career Content", data.get("application_content")),
        ("Cover Letter / Motivation Context", data.get("cover_letter")),
        ("Interview / Personal Positioning", data.get("about_narrative")),
        ("Additional Master-Profile Data", {
            key: value for key, value in data.items()
            if key not in {"_meta", "identity", "contact", "location", "privacy", "professional_profile",
                           "career_objective", "education", "experience", "skills", "ai_engineering",
                           "projects", "leadership", "achievements", "competitive_programming",
                           "job_preferences", "application_content", "cover_letter", "about_narrative"}
        }),
    ]

    lines = [
        "CANONICAL CANDIDATE PROFILE — SOURCE OF TRUTH",
        "Use this profile as the factual authority for matching. Do not invent missing facts.",
    ]
    for title, value in preferred_sections:
        lines.extend(_section(title, value))
    return "\n".join(lines)


def get_profile_text() -> str:
    """Backward-compatible alias used by existing callers."""
    return get_full_profile_text()
