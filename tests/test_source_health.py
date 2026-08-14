from utils.source_health import SourceHealth, build_search_summary, classify_exception, finalize_health


def test_classify_timeout_and_http_errors():
    assert classify_exception(TimeoutError("request timeout")) == "TIMEOUT"
    assert classify_exception(RuntimeError("HTTP 429 rate limit")) == "HTTP_429"
    assert classify_exception(RuntimeError("403 forbidden")) == "HTTP_403"


def test_zero_results_are_healthy_but_explicitly_marked():
    health = finalize_health(
        SourceHealth(name="Naukri", started_at="2026-08-14T03:00:00+00:00"),
        0,
    )
    assert health.status == "HEALTHY"
    assert health.error_classification == "NO_RESULTS"
    assert health.jobs_found == 0


def test_source_error_with_no_jobs_is_failed():
    health = SourceHealth(
        name="Naukri",
        started_at="2026-08-14T03:00:00+00:00",
        errors=["blocked"],
        error_classification="BLOCKED",
    )
    health = finalize_health(health, 0)
    assert health.status == "FAILED"


def test_source_error_with_partial_results_is_degraded():
    health = SourceHealth(
        name="LinkedIn",
        started_at="2026-08-14T03:00:00+00:00",
        errors=["one page failed"],
        error_classification="HTTP_429",
    )
    health = finalize_health(health, 5)
    assert health.status == "DEGRADED"


def test_search_summary_reports_source_diversity():
    health = {
        "Greenhouse": SourceHealth(name="Greenhouse", jobs_found=80),
        "Naukri": SourceHealth(name="Naukri", jobs_found=0),
    }
    summary = build_search_summary(
        source_health=health,
        raw_listings=100,
        unique_listings=90,
        source_breakdown={"Greenhouse": 80, "Naukri": 10},
        duplicate_count=10,
        duration_seconds=12.5,
        status="collection_complete",
    )
    assert summary["total_raw_jobs"] == 100
    assert summary["total_unique_jobs"] == 90
    assert summary["duplicate_count"] == 10
    assert summary["sources_enabled"] == 2
    assert summary["source_percentage"]["Greenhouse"] == round(80 / 90 * 100, 2)
