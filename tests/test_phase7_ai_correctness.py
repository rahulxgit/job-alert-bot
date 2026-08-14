import json
from pathlib import Path

import config
from ai.checkpoint import CHECKPOINT_VERSION, checkpoint_identity, compatible, evaluation_key, profile_hash
from ai.metrics import MetricsCoordinator
from ai.provider_limiter import ProviderBackoff


def test_metrics_record_exact_terminal_states(tmp_path):
    coordinator = MetricsCoordinator(tmp_path / "ai-progress.json")
    coordinator.record_candidate_start()
    coordinator.record_candidate_result(status="PASSED", duration_seconds=1.0)
    coordinator.record_candidate_start()
    coordinator.record_candidate_result(status="REJECTED", duration_seconds=2.0)
    coordinator.record_candidate_start()
    coordinator.record_candidate_result(status="UNRESOLVED", duration_seconds=3.0)

    assert coordinator.snapshot() == {
        "attempted": 3,
        "completed": 2,
        "unresolved": 1,
        "passed": 1,
        "rejected": 1,
        "retry_attempts": 0,
        "average_latency_seconds": 2.0,
        "p95_latency_seconds": 2.0,
    }


def test_checkpoint_identity_rejects_changed_candidate_set_or_profile():
    urls = ["https://example.com/a", "https://example.com/b"]
    digest = profile_hash("profile-v1")
    identity = checkpoint_identity(urls, digest)
    assert identity["checkpoint_version"] == CHECKPOINT_VERSION
    assert compatible(identity, urls, digest)
    assert not compatible(identity, ["https://example.com/a"], digest)
    assert not compatible(identity, urls, profile_hash("profile-v2"))


def test_evaluation_key_changes_when_description_changes():
    digest = profile_hash("profile")
    first = evaluation_key("https://example.com/a", "React role", digest)
    second = evaluation_key("https://example.com/a", "React + Node role", digest)
    assert first != second


def test_provider_backoff_is_shared_and_clearable(monkeypatch):
    backoff = ProviderBackoff()
    monkeypatch.setattr("ai.provider_limiter.time.monotonic", lambda: 100.0)
    assert not backoff.is_active()
    backoff.activate(10)
    assert backoff.is_active()
    backoff.clear()
    assert not backoff.is_active()
