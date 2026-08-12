"""Tests for the profile adapter."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.profile_adapter import load_canonical_profile, build_structured_profile, ProfileLoadError, MASTER_PROFILE_PATH
import json

def test_canonical_profile_loads():
    data = load_canonical_profile()
    assert data is not None
    assert "identity" in data

def test_profile_adapter_extraction():
    struct = build_structured_profile()
    assert struct["identity"]["career_stage"] == "entry-level"

    # Education test
    assert len(struct["education"]) > 0
    assert "Bio-Medical" in struct["education"][0]["branch"]

    # Text generation test
    text = struct["raw_text"]
    assert "Bio-Medical" in text
    assert "Computer Science (Fallback)" not in text

def test_profile_adapter_fails_safely(monkeypatch):
    import ai.profile_adapter
    monkeypatch.setattr(ai.profile_adapter, "MASTER_PROFILE_PATH", "/does/not/exist.json")

    try:
        data = build_structured_profile()
        assert False, "Should raise ProfileLoadError"
    except ProfileLoadError:
        assert True
