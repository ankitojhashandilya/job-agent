"""Evidence and outcome tests using recorded supported-ATS page snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from agent.ats import ATSCapability, ATSPlatform, assess_ats
from agent.evidence import make_review_evidence
from agent.types import ActionRecord, Button, FileInput, FormField, PageSnapshot
from application_runs import append_run, build_metrics, write_metrics


FIXTURES = Path(__file__).parent / "fixtures"


def load_snapshot(name: str) -> PageSnapshot:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return PageSnapshot(
        url=data["url"],
        page_title=data["page_title"],
        domain=data["domain"],
        page_type=data["page_type"],
        fields=[FormField(**field) for field in data["fields"]],
        file_inputs=[FileInput(**upload) for upload in data["file_inputs"]],
        buttons=[Button(**button) for button in data["buttons"]],
        error_messages=data["error_messages"],
    )


def timeline() -> list[ActionRecord]:
    return [ActionRecord("fill_field", "field:first_name", None, "ok", 1.0)]


def test_supported_ats_fixtures_are_detected_and_meet_review_contract(tmp_path):
    expectations = {
        "linkedin_easy_apply_review.json": ATSPlatform.LINKEDIN,
        "workday_review.json": ATSPlatform.WORKDAY,
        "greenhouse_review.json": ATSPlatform.GREENHOUSE,
    }
    screenshot = str(tmp_path / "review.png")
    for fixture, platform in expectations.items():
        snapshot = load_snapshot(fixture)
        assessment = assess_ats(snapshot)
        assert assessment.platform is platform
        assert assessment.capability is ATSCapability.SUPPORTED
        evidence = make_review_evidence(
            snapshot,
            application_form_opened=True,
            resume_uploaded=True,
            final_review_detected=True,
            screenshot_path=screenshot,
            timeline=timeline(),
        )
        assert evidence.verified
        assert evidence.to_dict()["snapshot"]["fields"][0]["filled"] is True
        assert "value" not in evidence.to_dict()["snapshot"]["fields"][0]


def test_review_ready_requires_every_piece_of_evidence(tmp_path):
    snapshot = load_snapshot("greenhouse_review.json")
    evidence = make_review_evidence(
        snapshot,
        application_form_opened=True,
        resume_uploaded=False,
        final_review_detected=True,
        screenshot_path=str(tmp_path / "review.png"),
        timeline=timeline(),
    )
    assert evidence.verified is False


def test_unknown_domain_is_not_a_supported_success():
    snapshot = PageSnapshot(
        url="https://careers.unknown-ats.example/apply",
        page_title="Apply",
        domain="careers.unknown-ats.example",
        page_type="application_form",
    )
    assert assess_ats(snapshot).capability is ATSCapability.UNSUPPORTED


def test_metrics_counts_only_verified_review_ready_runs():
    verified = {"verified": True}
    report = build_metrics(
        [
            {"eligible": True, "ats": "greenhouse", "status": "review_ready", "evidence": verified},
            {"eligible": True, "ats": "greenhouse", "status": "review_ready", "evidence": {"verified": False}},
            {"eligible": True, "ats": "workday", "status": "login_required", "evidence": {}},
            {"eligible": False, "ats": "unknown", "status": "review_ready", "evidence": verified},
        ]
    )
    assert report["overall"]["eligible_applications"] == 3
    assert report["overall"]["review_ready"] == 1
    assert report["overall"]["verified_review_ready_rate"] == 33.3
    assert report["by_ats"]["greenhouse"]["verified_review_ready_rate"] == 50.0


def test_run_persistence_and_metrics_output_are_local_json(tmp_path):
    runs = tmp_path / "application_runs.json"
    metrics = tmp_path / "application_metrics.json"
    append_run(
        {
            "eligible": True,
            "ats": "linkedin_easy_apply",
            "status": "review_ready",
            "evidence": {"verified": True},
        },
        path=runs,
    )
    report = write_metrics(runs_path=runs, destination=metrics)
    assert report["overall"]["verified_review_ready_rate"] == 100.0
    assert json.loads(metrics.read_text(encoding="utf-8"))["overall"]["review_ready"] == 1
