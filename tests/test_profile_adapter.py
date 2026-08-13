"""Tests for the canonical master-profile adapter."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.profile_adapter import (
    MASTER_PROFILE_PATH,
    ProfileLoadError,
    build_structured_profile,
    get_full_profile_text,
    load_canonical_profile,
)


def test_canonical_profile_loads():
    data = load_canonical_profile()
    assert data is not None
    assert "identity" in data
    assert data["_meta"]["single_source_of_truth"] is True


def test_profile_adapter_extraction():
    struct = build_structured_profile()
    assert struct["identity"]["career_stage"] == "entry-level"

    assert len(struct["education"]) > 0
    assert "Bio-Medical" in struct["education"][0]["branch"]

    text = struct["raw_text"]
    assert "Bio-Medical" in text
    assert "Computer Science (Fallback)" not in text


def test_profile_context_has_stable_matching_sections_and_excludes_secrets():
    text = get_full_profile_text()
    required_sections = (
        "Education", "Experience", "Skills", "AI Engineering", "Projects",
        "Leadership", "Achievements", "Competitive Programming / CP Profile",
        "Job Preferences", "Professional Profile", "Career Objective",
    )
    for section in required_sections:
        assert f"## {section}" in text
    assert "pin_code" not in text.lower()
    assert "api_keys" not in text.lower()
    assert "authentication_secrets" not in text.lower()


def test_master_profile_path_is_canonical():
    assert MASTER_PROFILE_PATH.endswith("data/rahul-master-profile.json")
    assert "profile-data.json" not in MASTER_PROFILE_PATH


def test_profile_adapter_fails_safely(monkeypatch):
    import ai.profile_adapter

    monkeypatch.setattr(ai.profile_adapter, "MASTER_PROFILE_PATH", "/does/not/exist.json")
    try:
        build_structured_profile()
        assert False, "Should raise ProfileLoadError"
    except ProfileLoadError:
        assert True
