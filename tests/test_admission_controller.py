from ai.admission_controller import admit_candidates, compute_admission_limit


class _Job:
    def __init__(self, url: str) -> None:
        self.job_url = url

    def to_dict(self) -> dict:
        return {"job_url": self.job_url}


def test_admission_limit_is_bounded_by_configured_max() -> None:
    decision = compute_admission_limit({
        "attempted": 10,
        "unresolved": 0,
        "average_latency_seconds": 20,
        "p95_latency_seconds": 30,
    })
    assert 40 <= decision["admitted_candidates"] <= 300
    assert decision["theoretical_capacity"] >= decision["admitted_candidates"] or decision["admitted_candidates"] == 300


def test_high_unresolved_rate_reduces_admission_capacity(monkeypatch) -> None:
    monkeypatch.setenv("MAX_LLM_CANDIDATES", "300")
    baseline = compute_admission_limit({
        "attempted": 100,
        "unresolved": 0,
        "average_latency_seconds": 90,
        "p95_latency_seconds": 120,
    })
    degraded = compute_admission_limit({
        "attempted": 100,
        "unresolved": 60,
        "average_latency_seconds": 90,
        "p95_latency_seconds": 120,
    })
    assert degraded["admitted_candidates"] < baseline["admitted_candidates"]
    assert degraded["reliability_factor"] < baseline["reliability_factor"]


def test_admission_uses_minimum_floor_on_bad_history(monkeypatch) -> None:
    monkeypatch.setenv("MAX_LLM_CANDIDATES", "60")
    decision = compute_admission_limit({
        "attempted": 100,
        "unresolved": 100,
        "average_latency_seconds": 1000,
        "p95_latency_seconds": 2000,
    })
    assert decision["admitted_candidates"] == 40


def test_admission_explicitly_records_deferred_candidates(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("ai.admission_controller.DEFERRED_ARTIFACT", tmp_path / "deferred.json")
    jobs = [_Job(f"https://example.com/{i}") for i in range(5)]
    admitted, deferred = admit_candidates(jobs, limit=3)
    assert len(admitted) == 3
    assert len(deferred) == 2
    assert deferred[0].job_url.endswith("/3")
    assert (tmp_path / "deferred.json").exists()
