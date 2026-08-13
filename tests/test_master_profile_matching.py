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


def test_jd_prompt_uses_full_profile_and_anti_fabrication_rules():
    prompt = _build_prompt(JobListing(
        job_url="https://example.com/job/1",
        title="Software Engineer",
        company="Example",
        location="Bengaluru",
        description="React, Node.js, REST APIs; 0-1 years experience.",
    ))
    assert "CANONICAL CANDIDATE PROFILE" in prompt
    assert "Competitive Programming / CP Profile" in prompt
    assert "Never invent or assume" in prompt
    assert "education" in prompt.lower()
    assert "projects" in prompt.lower()
    assert "cover-letter" in prompt.lower()


def test_legacy_profile_path_is_not_used_by_runtime_loader():
    assert "profile-data.json" not in MASTER_PROFILE_PATH
    assert MASTER_PROFILE_PATH.endswith("rahul-master-profile.json")
