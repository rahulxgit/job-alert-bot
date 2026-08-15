from pathlib import Path

import ai.provider_state as provider_state


def test_timeout_then_recovery_transitions_state(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "provider-state.json"
    monkeypatch.setattr(provider_state, "_PROVIDER_ARTIFACT", artifact)
    provider_state.reset_for_tests()

    provider_state.record_request("AI Gateway")
    provider_state.record_failure("AI Gateway", "TIMEOUT", latency_seconds=2.0)
    snapshot = provider_state.snapshot()["AI Gateway"]
    assert snapshot["state"] == "TIMEOUTING"
    assert snapshot["timeouts"] == 1

    provider_state.record_success("AI Gateway", latency_seconds=1.0)
    snapshot = provider_state.snapshot()["AI Gateway"]
    assert snapshot["state"] == "AVAILABLE"
    assert snapshot["consecutive_failures"] == 0
    assert snapshot["recovery_count"] == 1
    assert Path(artifact).exists()


def test_repeated_failures_open_telemetry_circuit() -> None:
    provider_state.reset_for_tests()
    for _ in range(3):
        provider_state.record_failure("Gemini", "RATE_LIMITED", latency_seconds=1.0)
    snapshot = provider_state.snapshot()["Gemini"]
    assert snapshot["state"] == "CIRCUIT_OPEN"
    assert snapshot["rate_limits"] == 3
