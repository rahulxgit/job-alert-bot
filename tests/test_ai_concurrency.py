import json
import time
from pathlib import Path

import ai.evaluator as evaluator
import config
from models import FitVerdict, JobListing


def _job(index: int) -> JobListing:
    return JobListing(
        job_url=f"https://example.com/jobs/{index}",
        title="Software Engineer",
        company="Example Co",
        location="Bengaluru, India",
        description="React Node.js MongoDB fresher entry level",
        source="Test",
    )


def _verdict() -> FitVerdict:
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


def test_ai_reviews_run_concurrently_and_checkpoint_is_valid(tmp_path, monkeypatch):
    progress_path = tmp_path / "run-artifacts" / "ai-progress.json"
    failed_path = tmp_path / "failed-ai-jobs.json"
    monkeypatch.setattr(evaluator, "AI_PROGRESS_PATH", progress_path)
    monkeypatch.setattr(evaluator, "FAILED_AI_JOBS_PATH", failed_path)
    monkeypatch.setattr(config, "MAX_LLM_CANDIDATES", 4)
    monkeypatch.setattr(config, "AI_MAX_CONCURRENCY", 4)

    active = 0
    max_active = 0

    def fake_eval(job, skip_gemini_retries=False, deadline=None):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        time.sleep(0.05)
        active -= 1
        return _verdict(), False

    monkeypatch.setattr(evaluator, "evaluate_listing", fake_eval)

    reviewed = evaluator.review_candidates([_job(i) for i in range(4)], deadline=time.monotonic() + 10)

    assert len(reviewed) == 4
    assert max_active > 1

    checkpoint = json.loads(progress_path.read_text(encoding="utf-8"))
    assert checkpoint["status"] == "completed"
    assert checkpoint["evaluated_count"] == 4
    assert checkpoint["metrics"]["completed"] == 4


def test_unresolved_jobs_remain_in_retry_queue(tmp_path, monkeypatch):
    progress_path = tmp_path / "run-artifacts" / "ai-progress.json"
    failed_path = tmp_path / "failed-ai-jobs.json"
    monkeypatch.setattr(evaluator, "AI_PROGRESS_PATH", progress_path)
    monkeypatch.setattr(evaluator, "FAILED_AI_JOBS_PATH", failed_path)
    monkeypatch.setattr(config, "MAX_LLM_CANDIDATES", 2)
    monkeypatch.setattr(config, "AI_MAX_CONCURRENCY", 2)

    def fake_eval(job, skip_gemini_retries=False, deadline=None):
        if job.job_url.endswith("/1"):
            return None, True
        return _verdict(), False

    monkeypatch.setattr(evaluator, "evaluate_listing", fake_eval)

    reviewed = evaluator.review_candidates([_job(0), _job(1)], deadline=time.monotonic() + 10)

    assert [job.job_url for job in reviewed] == [_job(0).job_url]
    payload = json.loads(failed_path.read_text(encoding="utf-8"))
    assert [job["job_url"] for job in payload["jobs"]] == [_job(1).job_url]
