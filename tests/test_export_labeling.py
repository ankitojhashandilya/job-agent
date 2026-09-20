import csv
import json

import apply_top_jobs
import discovery
from config import PROJECT_DIR


def test_discovery_export_shape(tmp_path, monkeypatch):
    json_path = tmp_path / "job_results.json"
    csv_path = tmp_path / "job_results.csv"
    monkeypatch.setattr(discovery, "JOB_RESULTS_JSON", json_path)
    monkeypatch.setattr(discovery, "JOB_RESULTS_CSV", csv_path)

    results = [
        {
            "company": "Acme",
            "title": "Engineer",
            "location": "Remote",
            "url": "https://example.com/job",
            "search_keyword": "engineer",
            "match_score": 80,
            "status": "applied",
            "reason": "good fit",
            "matched_skills": ["python", "aws"],
            "missing_skills": ["k8s"],
            "subscores": {
                "technical_fit": 8,
                "seniority": 7,
                "leadership": 5,
                "location": 6,
                "domain": 7,
                "growth": 6,
            },
        }
    ]

    discovery._persist(results)

    # JSON output stays a plain list — existing consumers depend on this.
    assert json.loads(json_path.read_text(encoding="utf-8")) == results

    # CSV output stays a plain table with a header row.
    with csv_path.open(encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1
    assert rows[0]["company"] == "Acme"
    assert rows[0]["technical_fit"] == "8"
    assert rows[0]["matched_skills"] == "python, aws"

    # Companion export marker labels the files as exports, not the
    # system of record.
    marker = json.loads(
        (tmp_path / "job_results.export.json").read_text(encoding="utf-8")
    )
    assert marker["_export"] is True
    assert marker["kind"] == discovery.EXPORT_KIND
    assert marker["system_of_record"] == discovery.EXPORT_SYSTEM_OF_RECORD
    assert marker["files"] == ["job_results.json", "job_results.csv"]


def test_discovery_export_marker_names_match_system_of_record():
    assert discovery.EXPORT_SYSTEM_OF_RECORD == "job_history.json"
    assert PROJECT_DIR.name == "job-agent"


def test_applications_export_shape(tmp_path, monkeypatch):
    json_path = tmp_path / "applications.json"
    csv_path = tmp_path / "applications.csv"
    monkeypatch.setattr(apply_top_jobs, "APPLICATIONS_JSON", json_path)
    monkeypatch.setattr(apply_top_jobs, "APPLICATIONS_CSV", csv_path)

    records = [
        {
            "timestamp": "2026-08-03T00:00:00",
            "company": "Acme",
            "title": "Engineer",
            "location": "Remote",
            "url": "https://example.com/job",
            "match_score": 80,
            "apply_type": "linkedin",
            "apply_url": "https://example.com/apply",
            "status": "submitted",
            "resume_uploaded": True,
            "fields_filled": ["name", "email"],
            "screenshot": "",
            "notes": "",
        }
    ]

    apply_top_jobs.save_applications(records)

    # JSON output stays a plain list.
    assert json.loads(json_path.read_text(encoding="utf-8")) == records

    # CSV output stays a plain table.
    with csv_path.open(encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1
    assert rows[0]["company"] == "Acme"
    assert rows[0]["fields_filled"] == "name, email"

    # Companion export marker labels the files as exports.
    marker = json.loads(
        (tmp_path / "applications.export.json").read_text(encoding="utf-8")
    )
    assert marker["_export"] is True
    assert marker["kind"] == "applications"
    assert marker["system_of_record"] == "job_history.json"
    assert marker["files"] == ["applications.json", "applications.csv"]
