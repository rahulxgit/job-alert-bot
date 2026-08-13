import json

from models import JobListing
from utils import run_artifacts


def test_export_stage_writes_json_and_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(run_artifacts, "ARTIFACT_DIR", tmp_path)
    listing = JobListing(
        job_url="https://example.com/job/1",
        title="Software Engineer",
        company="Example",
        location="Bengaluru",
        description="React and Node.js",
        source="test",
        fit_score=88,
        gaps=["AWS"],
    )

    run_artifacts.export_stage("final-reviewed", [listing], metadata={"threshold": 70})

    payload = json.loads((tmp_path / "final-reviewed.json").read_text(encoding="utf-8"))
    assert payload["stage"] == "final-reviewed"
    assert payload["count"] == 1
    assert payload["metadata"]["threshold"] == 70
    assert payload["jobs"][0]["job_url"] == listing.job_url
    assert payload["jobs"][0]["fit_score"] == 88
    assert payload["jobs"][0]["gaps"] == ["AWS"]

    csv_text = (tmp_path / "final-reviewed.csv").read_text(encoding="utf-8")
    assert "job_url" in csv_text
    assert "Software Engineer" in csv_text
    assert "AWS" in csv_text
