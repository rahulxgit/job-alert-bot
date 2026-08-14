import json
import time

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
        role_match=20,
        experience_match=18,
        technical_match=22,
        project_match=8,
        education_match=8,
        location_match=5,
        company_quality=4,
    )


def test_ai_deadline_stops_new_work_and_keeps_checkpoint_resumable(tmp_path, monkeypatch):
    progress_path = tmp_path / "run-artifacts" / "ai-progress.json"
    failed_path = tmp_path / "failed-ai-jobs.json"
    monkeypatch.setattr(evaluator, "AI_PROGRESS_PATH", progress_path)
    monkeypatch.setattr(evaluator, "FAILED_AI_JOBS_PATH", failed_path)
    monkeypatch.setattr(config, "MAX_LLM_CANDIDATES", 4)
    monkeypatch.setattr(config, "AI_MAX_CONCURRENCY", 2)

    def fake_eval(job, skip_gemini_retries=False, deadline=None):
        return _verdict(), False

    monkeypatch.setattr(evaluator, "evaluate_listing", fake_eval)

    reviewed = evaluator.review_candidates([_job(i) for i in range(4)], deadline=time.monotonic() - 1)

    assert reviewed == []
    checkpoint = json.loads(progress_path.read_text(encoding="utf-8"))
    assert checkpoint["status"] == "deadline_exceeded"
    assert checkpoint["evaluated_count"] == 0
    retry_payload = json.loads(failed_path.read_text(encoding="utf-8"))
    assert retry_payload["count"] == 4
