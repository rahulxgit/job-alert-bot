import json

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


def test_checkpoint_resumes_after_worker_interruption(tmp_path, monkeypatch):
    progress_path = tmp_path / "run-artifacts" / "ai-progress.json"
    failed_path = tmp_path / "failed-ai-jobs.json"
    monkeypatch.setattr(evaluator, "AI_PROGRESS_PATH", progress_path)
    monkeypatch.setattr(evaluator, "FAILED_AI_JOBS_PATH", failed_path)
    monkeypatch.setattr(config, "MAX_LLM_CANDIDATES", 5)
    monkeypatch.setattr(config, "AI_MAX_CONCURRENCY", 4)

    jobs = [_job(i) for i in range(5)]

    def interrupted_eval(job, skip_gemini_retries=False, deadline=None):
        if job.job_url.endswith("/2"):
            raise RuntimeError("simulated worker interruption")
        return _verdict(), False

    monkeypatch.setattr(evaluator, "evaluate_listing", interrupted_eval)
    first_review = evaluator.review_candidates(jobs)

    assert len(first_review) == 4
    checkpoint = json.loads(progress_path.read_text(encoding="utf-8"))
    assert checkpoint["status"] == "completed"
    assert jobs[2].job_url not in checkpoint["evaluated_jobs"]
    assert set(checkpoint["evaluated_jobs"]) == {
        jobs[0].job_url,
        jobs[1].job_url,
        jobs[3].job_url,
        jobs[4].job_url,
    }

    failed = json.loads(failed_path.read_text(encoding="utf-8"))
    assert [job["job_url"] for job in failed["jobs"]] == [jobs[2].job_url]

    resumed_calls = []

    def resumed_eval(job, skip_gemini_retries=False, deadline=None):
        resumed_calls.append(job.job_url)
        return _verdict(), False

    monkeypatch.setattr(evaluator, "evaluate_listing", resumed_eval)
    reviewed = evaluator.review_candidates(jobs)

    # The unresolved job is retried first; the remaining new candidates are then
    # eligible for the same run. Completion order is intentionally nondeterministic
    # because the evaluator uses a bounded worker pool.
    assert resumed_calls[0] == jobs[2].job_url
    assert set(resumed_calls) == {job.job_url for job in jobs}
    assert len(resumed_calls) == 5
    assert len(reviewed) == 5

    final_checkpoint = json.loads(progress_path.read_text(encoding="utf-8"))
    assert final_checkpoint["status"] == "completed"
    assert final_checkpoint["evaluated_count"] == 5
