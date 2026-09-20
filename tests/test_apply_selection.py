"""Eligibility checks that guard the UI's Apply Top Jobs action."""

import json

import apply_top_jobs


def _job(*, url: str, score: int, status: str) -> dict:
    return {
        "company": "Acme",
        "title": "Data Engineer",
        "url": url,
        "match_score": score,
        "status": status,
    }


def test_rejected_placeholder_job_is_never_actionable():
    job = _job(url="https://x.test/1", score=39, status="Reject")

    assert apply_top_jobs.is_actionable_job(job) is False


def test_apply_job_requires_live_url_and_threshold():
    assert apply_top_jobs.is_actionable_job(
        _job(url="https://www.linkedin.com/jobs/view/123", score=90, status="Apply")
    )
    assert not apply_top_jobs.is_actionable_job(
        _job(url="https://x.test/1", score=100, status="Apply")
    )
    assert not apply_top_jobs.is_actionable_job(
        _job(url="https://www.linkedin.com/jobs/view/123", score=74, status="Apply")
    )


def test_top_jobs_returns_only_eligible_apply_rows(tmp_path, monkeypatch):
    results_path = tmp_path / "job_results.json"
    results_path.write_text(
        json.dumps(
            [
                _job(url="https://x.test/1", score=100, status="Apply"),
                _job(url="https://www.linkedin.com/jobs/view/reject", score=99, status="Reject"),
                _job(url="https://www.linkedin.com/jobs/view/real", score=90, status="Apply"),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(apply_top_jobs, "JOB_RESULTS_PATH", results_path)

    assert [job["url"] for job in apply_top_jobs.top_jobs()] == [
        "https://www.linkedin.com/jobs/view/real"
    ]


def test_only_known_pre_navigation_quic_failure_is_retryable():
    assert apply_top_jobs.is_retryable_application_record(
        {"status": "failed", "notes": "Page.goto: net::ERR_QUIC_PROTOCOL_ERROR"}
    )
    assert not apply_top_jobs.is_retryable_application_record(
        {"status": "failed", "notes": "required question could not be answered"}
    )


def test_network_access_denied_before_navigation_is_retryable():
    assert apply_top_jobs.is_retryable_application_record(
        {"status": "failed", "notes": "Page.goto: net::ERR_NETWORK_ACCESS_DENIED"}
    )


def test_login_required_is_retryable_after_manual_authentication():
    assert apply_top_jobs.is_retryable_application_record(
        {"status": "login_required", "notes": "Login is required."}
    )


def test_legacy_pre_form_manual_handoff_is_retryable_after_adapter_fix():
    assert apply_top_jobs.is_retryable_application_record(
        {
            "status": "manual_required",
            "notes": "No recognized safe action is available on this page.",
        }
    )


def test_external_apply_confirmation_handoff_is_retryable():
    assert apply_top_jobs.is_retryable_application_record(
        {"status": "external_apply_confirmation_required", "notes": "profile sharing needs approval"}
    )


def test_linkedin_progress_toast_false_failure_is_retryable():
    assert apply_top_jobs.is_retryable_application_record(
        {
            "status": "failed",
            "evidence": {
                "snapshot": {
                    "error_messages": ["Job moved to In progress under Clicked apply."],
                }
            },
        }
    )
