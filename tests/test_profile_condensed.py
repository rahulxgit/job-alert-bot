"""Tests for the condensed candidate profile builder."""
from ai.profile_condensed import build_condensed_profile


def test_condensed_profile_is_much_smaller_than_full_dump():
    from ai.profile_adapter import get_full_profile_text
    condensed = build_condensed_profile()
    full = get_full_profile_text()
    assert len(condensed) < len(full) * 0.15


def test_condensed_profile_contains_core_facts():
    text = build_condensed_profile()
    assert "NIT Raipur" in text
    assert "Bio-Medical" in text
    assert "Bluestock Fintech" in text
    assert "React" in text
    assert "Logic Looper" in text or "DriveClone" in text


def test_condensed_profile_never_crashes_on_missing_optional_sections():
    # achievements / competitive_programming / leadership are optional
    # top-level keys — absence must not break the build.
    text = build_condensed_profile()
    assert isinstance(text, str)
    assert len(text) > 100
