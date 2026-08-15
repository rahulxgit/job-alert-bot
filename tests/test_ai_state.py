from ai.state import EvaluationState, PASSED, RETRYABLE_ERROR, DEADLINE_EXCEEDED, EVALUATING, from_dict
from ai.state_migration import migrate_legacy_progress, migrate_legacy_retry_jobs
from ai.state_store import AIStateStore


def test_state_transition_and_attempt_accounting() -> None:
    state = EvaluationState("https://example.com/job")
    state.start_attempt("Gemini")
    assert state.status == EVALUATING
    assert state.attempts == 1
    state.transition(RETRYABLE_ERROR, error="rate_limited")
    assert state.status == RETRYABLE_ERROR
    assert state.last_error == "rate_limited"


def test_deadline_state_is_resumable() -> None:
    state = EvaluationState("https://example.com/job", status=DEADLINE_EXCEEDED)
    assert state.status == DEADLINE_EXCEEDED


def test_state_round_trip_and_legacy_aliases() -> None:
    original = EvaluationState("https://example.com/job", status=RETRYABLE_ERROR, attempts=2, last_error="timeout")
    restored = from_dict({**original.to_dict(), "status": "FAILED"})
    assert restored is not None
    assert restored.status == RETRYABLE_ERROR
    assert restored.attempts == 2


def test_legacy_progress_and_retry_queue_migrate() -> None:
    progress = migrate_legacy_progress({
        "evaluated_jobs": {
            "https://example.com/job": {
                "job_url": "https://example.com/job",
                "fit_score": 82,
                "fresher_appropriate": True,
                "evaluation_key": "k1",
            }
        }
    })
    retry = migrate_legacy_retry_jobs([
        {"job_url": "https://example.com/retry", "attempts": 3, "last_error": "timeout"}
    ])
    assert progress[0].status == PASSED
    assert retry[0].status == RETRYABLE_ERROR


def test_store_is_atomic_and_authoritative(tmp_path) -> None:
    store = AIStateStore(tmp_path / "ai-state.json")
    state = EvaluationState("https://example.com/job", status=PASSED, attempts=1)
    store.upsert(state)

    loaded = AIStateStore(tmp_path / "ai-state.json")
    restored = loaded.get("https://example.com/job")
    assert restored is not None
    assert restored.status == PASSED
    assert restored.attempts == 1
