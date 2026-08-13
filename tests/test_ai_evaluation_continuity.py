"""Regression tests ensuring provider failures never drop selected candidates."""

from models import FitVerdict, JobListing
import ai.evaluator as evaluator
import config


def _listing(index: int) -> JobListing:
    return JobListing(
        job_url=f"https://example.com/jobs/{index}",
        title="Software Engineer",
        description="React Node.js MongoDB fresher entry level",
        location="Bengaluru, India",
        source="Test",
    )


def test_all_selected_candidates_are_attempted_when_gateway_fails(monkeypatch):
    candidates = [_listing(i) for i in range(8)]
    gateway_calls = 0
    gemini_calls = 0

    def gateway_failure(_prompt):
        nonlocal gateway_calls
        gateway_calls += 1
        return None

    def gemini_success(_prompt, skip_retries=False):
        nonlocal gemini_calls
        gemini_calls += 1
        return FitVerdict(
            fit_score=85,
            is_fresher_appropriate=True,
            reason="matched",
            role_match=20,
            experience_match=18,
            technical_match=22,
            project_match=8,
            education_match=8,
            location_match=5,
            company_quality=4,
        )

    monkeypatch.setattr(evaluator._gateway, "evaluate", gateway_failure)
    monkeypatch.setattr(evaluator._gemini, "evaluate", gemini_success)
    monkeypatch.setattr(config, "MAX_LLM_CANDIDATES", len(candidates))

    reviewed = evaluator.review_candidates(candidates)

    assert gateway_calls == len(candidates)
    assert gemini_calls == len(candidates)
    assert len(reviewed) == len(candidates)


def test_gemini_rate_limit_does_not_skip_later_candidates(monkeypatch):
    candidates = [_listing(i) for i in range(4)]
    calls = []

    monkeypatch.setattr(evaluator._gateway, "evaluate", lambda _prompt: None)

    def gemini_result(_prompt, skip_retries=False):
        calls.append(skip_retries)
        if len(calls) == 1:
            return FitVerdict(hit_rate_limit=True, reason="rate limited")
        return FitVerdict(
            fit_score=85,
            is_fresher_appropriate=True,
            reason="matched",
            role_match=20,
            experience_match=18,
            technical_match=22,
            project_match=8,
            education_match=8,
            location_match=5,
            company_quality=4,
        )

    monkeypatch.setattr(evaluator._gemini, "evaluate", gemini_result)
    monkeypatch.setattr(config, "MAX_LLM_CANDIDATES", len(candidates))

    reviewed = evaluator.review_candidates(candidates)

    assert len(calls) == len(candidates)
    assert calls[0] is False
    assert all(value is True for value in calls[1:])
    assert len(reviewed) == len(candidates) - 1
