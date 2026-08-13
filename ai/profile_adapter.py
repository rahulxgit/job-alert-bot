"""Canonical career-profile loader for job matching and application context.

Only data/rahul-master-profile.json is read. Private contact fields and
secrets are excluded from model context, while raw_text compatibility is
preserved for existing tests/callers.
"""
from __future__ import annotations

import json
import os
from typing import Any

from utils.logging_setup import get_logger

log = get_logger("profile_adapter")
MASTER_PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "rahul-master-profile.json",
)

class ProfileLoadError(Exception):
    pass

_PRIVATE_OR_SECRET_KEYS = {
    "phone", "pin_code", "full_address", "password", "passwords", "api_key", "api_keys",
    "token", "tokens", "cookie", "cookies", "authentication_secrets", "secrets",
    "refresh_token", "access_token", "client_secret", "private_key", "resume_pdf",
}

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

def _section(title: str, value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    return [f"\n## {title}\n{json.dumps(value, ensure_ascii=False, indent=2)}"]

def get_full_profile_text(data: dict[str, Any] | None = None) -> str:
    if data is None:
        data = _sanitize_for_matching(load_canonical_profile())
    preferred_sections = [
        ("Identity & Career Stage", data.get("identity")),
        ("Contact & Public Profiles", data.get("contact")),
        ("Location & Work Preferences", data.get("location")),
        ("Professional Profile", data.get("professional_profile")),
        ("Career Objective", data.get("career_objective")),
        ("Education", data.get("education")),
        ("Experience", data.get("experience")),
        ("Skills", data.get("skills") or data.get("technical_skills") or data.get("technical_profile")),
        ("AI Engineering", data.get("ai_engineering")),
        ("Projects", data.get("projects")),
        ("Leadership", data.get("leadership")),
        ("Achievements", data.get("achievements")),
        ("Competitive Programming / CP Profile", data.get("competitive_programming")),
        ("Job Preferences", data.get("job_preferences")),
        ("Application / Career Content", data.get("application_content")),
        ("Cover Letter / Motivation Context", data.get("cover_letter") or data.get("motivation")),
        ("Interview / Personal Positioning", data.get("about_narrative")),
    ]
    used_keys = {key for key, value in preferred_sections if value not in (None, "", [], {})}
    remaining = {
        key: value for key, value in data.items()
        if key not in {"_meta", "privacy", *used_keys}
    }
    preferred_sections.append(("Additional Master-Profile Data", remaining))
    lines = [
        "CANONICAL CANDIDATE PROFILE — SOURCE OF TRUTH",
        "Use this profile as the factual authority for matching. Do not invent missing facts.",
    ]
    for title, value in preferred_sections:
        lines.extend(_section(title, value))
    return "\n".join(lines)

def build_structured_profile() -> dict[str, Any]:
    data = _sanitize_for_matching(load_canonical_profile())
    assert isinstance(data, dict)
    raw_text = get_full_profile_text(data)
    return {
        **data,
        "identity": {
            "career_stage": data.get("identity", {}).get("career_stage", "entry-level"),
            "name": data.get("identity", {}).get("full_name", ""),
        },
        "raw_text": raw_text,
    }

def get_profile_text() -> str:
    return get_full_profile_text()
