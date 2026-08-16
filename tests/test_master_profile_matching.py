from ai.evaluator import _build_prompt
from ai.profile_adapter import MASTER_PROFILE_PATH, get_full_profile_text, load_canonical_profile
from models import JobListing


def test_master_profile_is_canonical_source():
    assert MASTER_PROFILE_PATH.endswith("data/rahul-master-profile.json")
    data = load_canonical_profile()
    assert data["_meta"]["single_source_of_truth"] is True


def test_profile_context_contains_major_matching_dimensions_without_secrets():
    text = get_full_profile_text()
    for section in (
        "Education", "Experience", "Skills", "AI Engineering", "Projects",
        "Leadership", "Achievements", "Competitive Programming / CP Profile",
        "Job Preferences", "Professional Profile", "Career Objective",
    ):
        assert f"## {section}" in text
    assert "pin_code" not in text.lower()
    assert "api_keys" not in text.lower()
    assert "authentication_secrets" not in text.lower()


def test_jd_prompt_uses_condensed_profile_by_default_and_anti_fabrication_rules():
    prompt = _build_prompt(JobListing(
        job_url="https://example.com/job/1",
        title="Software Engineer",
        company="Example",
        location="Bengaluru",
        description="React, Node.js, REST APIs; 0-1 years experience.",
    ))
    assert "CANDIDATE PROFILE (condensed)" in prompt
    assert "Never invent or assume" in prompt
    assert "education" in prompt.lower()
    assert "projects" in prompt.lower()
    # Condensed mode should be meaningfully smaller than the full dump —
    # that's the whole point of the change (fewer tokens, faster calls,
    # fewer UNRESOLVED evaluations from provider timeouts).
    assert len(prompt) < 8000


def test_jd_prompt_can_still_use_full_profile_when_configured(monkeypatch):
    import config
    import ai.evaluator as evaluator
    monkeypatch.setattr(config, "AI_PROFILE_MODE", "full")
    monkeypatch.setattr(evaluator, "_candidate_profile", None)
    prompt = _build_prompt(JobListing(
        job_url="https://example.com/job/2",
        title="Software Engineer",
        company="Example",
        location="Bengaluru",
        description="React, Node.js, REST APIs; 0-1 years experience.",
    ))
    assert "CANONICAL CANDIDATE PROFILE" in prompt
    assert "Competitive Programming / CP Profile" in prompt
    # reset the module-level cache so other tests don't inherit "full" mode
    monkeypatch.setattr(evaluator, "_candidate_profile", None)


def test_legacy_profile_path_is_not_used_by_runtime_loader():
    assert "profile-data.json" not in MASTER_PROFILE_PATH
    assert MASTER_PROFILE_PATH.endswith("rahul-master-profile.json")
