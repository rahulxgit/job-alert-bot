from datetime import datetime, timedelta, timezone

import pytest

from ai.provider_state import record_request, reset_thread_context
from ai.state import (
    DEADLINE_EXCEEDED,
    EVALUATING,
    PASSED,
    REJECTED,
    RETRYABLE_ERROR,
    PERMANENT_ERROR,
    EvaluationState,
    from_dict,
)
from ai.state_migration import (
    migrate_legacy_progress,
    migrate_legacy_retry_jobs,
    resolve_migration_conflicts,
)
from ai.state_store import AIStateStore


def test_state_transition_and_attempt_accounting() -> None:
    reset_thread_context()
    state = EvaluationState("https://example.com/job")
    state.start_attempt("Gemini")
    record_request("Gemini")
    assert state.status == EVALUATING
    assert state.attempts == 1
    assert state.run_id
    assert state.lease_expires_at
    state.transition(RETRYABLE_ERROR, error="rate_limited")
    assert state.status == RETRYABLE_ERROR
    assert state.last_error == "rate_limited"
    assert state.provider == "Gemini"
    assert state.provider_attempts == 1


def test_queued_failure_compounds_to_retryable_attempt() -> None:
    state = EvaluationState("https://example.com/job")
    state.transition(RETRYABLE_ERROR, error="worker crashed")
    assert state.status == RETRYABLE_ERROR
    assert state.attempts == 1
    assert state.run_id
    assert state.evaluation_started_at
    assert state.lease_expires_at


def test_deadline_state_is_resumable() -> None:
    state = EvaluationState("https://example.com/job", status=DEADLINE_EXCEEDED)
    assert state.status == DEADLINE_EXCEEDED


def test_illegal_terminal_transition_is_rejected() -> None:
    state = EvaluationState("https://example.com/job", status=PASSED)
    with pytest.raises(ValueError, match="invalid AI state transition"):
        state.transition(RETRYABLE_ERROR, error="timeout")


def test_permanent_error_is_reached_for_unrecoverable_failure() -> None:
    state = EvaluationState("https://example.com/job")
    state.start_attempt()
    state.transition(RETRYABLE_ERROR, error="INVALID_RESPONSE")
    assert state.status == PERMANENT_ERROR


def test_terminal_state_clears_retry_metadata_but_preserves_permanent_reason() -> None:
    state = EvaluationState(
        "https://example.com/job",
        status=RETRYABLE_ERROR,
        last_error="timeout",
        next_retry_at="2099-01-01T00:00:00+00:00",
    )
    state.transition(EVALUATING)
    state.transition(PERMANENT_ERROR, error="unsupported configuration")
    assert state.status == PERMANENT_ERROR
    assert state.last_error == "unsupported configuration"
    assert state.next_retry_at is None
    assert state.lease_expires_at is None


def test_successful_terminal_state_clears_retry_metadata() -> None:
    state = EvaluationState(
        "https://example.com/job",
        status=RETRYABLE_ERROR,
        last_error="timeout",
        next_retry_at="2099-01-01T00:00:00+00:00",
    )
    state.transition(EVALUATING)
    state.transition(EVALUATED)
    state.transition(PASSED)
    assert state.last_error is None
    assert state.next_retry_at is None


def test_stale_evaluating_state_becomes_retryable() -> None:
    stale = EvaluationState(
        "https://example.com/job",
        status=EVALUATING,
        lease_expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    )
    stale.mark_stale()
    assert stale.status == RETRYABLE_ERROR
    assert stale.last_error == "stale_evaluation_lease"


def test_state_round_trip_and_legacy_aliases() -> None:
    original = EvaluationState("https://example.com/job", status=RETRYABLE_ERROR, attempts=2, last_error="timeout")
    restored = from_dict({**original.to_dict(), "status": "FAILED"})
    assert restored is not None
    assert restored.status == RETRYABLE_ERROR
    assert restored.attempts == 2


def test_future_state_version_is_rejected() -> None:
    state = EvaluationState("https://example.com/job")
    payload = {**state.to_dict(), "version": 999}
    assert from_dict(payload) is None


def test_legacy_progress_preserves_acceptance_semantics() -> None:
    progress = migrate_legacy_progress({
        "evaluated_jobs": {
            "https://example.com/pass": {
                "job_url": "https://example.com/pass",
                "fit_score": 82,
                "fresher_appropriate": True,
                "decision": "good_match",
                "evaluation_key": "k1",
            },
            "https://example.com/reject": {
                "job_url": "https://example.com/reject",
                "fit_score": 95,
                "fresher_appropriate": True,
                "decision": "reject",
                "evaluation_key": "k2",
            },
        }
    })
    by_url = {state.job_url: state.status for state in progress}
    assert by_url["https://example.com/pass"] == PASSED
    assert by_url["https://example.com/reject"] == REJECTED


def test_terminal_legacy_state_wins_over_retry_duplicate() -> None:
    progress = migrate_legacy_progress({
        "evaluated_jobs": {
            "https://example.com/job": {
                "job_url": "https://example.com/job",
                "fit_score": 90,
                "fresher_appropriate": True,
                "decision": "good_match",
            }
        }
    })
    retry = migrate_legacy_retry_jobs([
        {"job_url": "https://example.com/job", "attempts": 5, "last_error": "timeout"}
    ])
    resolved = resolve_migration_conflicts(progress + retry)
    assert len(resolved) == 1
    assert resolved[0].status == PASSED


def test_malformed_legacy_attempts_do_not_crash() -> None:
    progress = migrate_legacy_progress({
        "evaluated_jobs": {
            "https://example.com/job": {
                "job_url": "https://example.com/job",
                "fit_score": 80,
                "fresher_appropriate": True,
                "decision": "good_match",
                "attempts": "not-an-int",
            }
        }
    })
    retry = migrate_legacy_retry_jobs([
        {"job_url": "https://example.com/retry", "attempts": {"bad": "value"}}
    ])
    assert progress[0].attempts == 1
    assert retry[0].attempts == 0


def test_legacy_retry_queue_migrates_to_retryable() -> None:
    retry = migrate_legacy_retry_jobs([
        {"job_url": "https://example.com/retry", "attempts": 3, "last_error": "timeout"}
    ])
    assert retry[0].status == RETRYABLE_ERROR
    assert retry[0].attempts == 3


def test_store_preserves_updates_from_two_instances(tmp_path) -> None:
    path = tmp_path / "ai-state.json"
    store_a = AIStateStore(path)
    store_b = AIStateStore(path)
    store_a.upsert(EvaluationState("https://example.com/job-1", status=PASSED))
    store_b.upsert(EvaluationState("https://example.com/job-2", status=REJECTED))
    store_a.upsert(EvaluationState("https://example.com/job-3", status=PASSED))

    loaded = AIStateStore(path).load()
    assert set(loaded) == {
        "https://example.com/job-1",
        "https://example.com/job-2",
        "https://example.com/job-3",
    }


def test_store_is_atomic_and_authoritative(tmp_path) -> None:
    store = AIStateStore(tmp_path / "ai-state.json")
    state = EvaluationState("https://example.com/job", status=PASSED, attempts=1)
    store.upsert(state)

    loaded = AIStateStore(tmp_path / "ai-state.json")
    restored = loaded.get("https://example.com/job")
    assert restored is not None
    assert restored.status == PASSED
    assert restored.attempts == 1
