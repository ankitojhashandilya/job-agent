"""Failure-path coverage for the production browser-agent wrapper."""

from unittest.mock import MagicMock, patch

import apply_top_jobs


def test_browser_agent_exception_returns_a_failed_record(tmp_path, monkeypatch):
    page = MagicMock()
    page.url = "https://www.linkedin.com/jobs/view/123"
    context = MagicMock()
    context.new_page.return_value = page
    monkeypatch.setattr(apply_top_jobs, "SCREENSHOT_DIR", tmp_path)

    job = {
        "company": "Acme",
        "title": "Data Engineer",
        "location": "Remote",
        "url": page.url,
        "match_score": 80,
    }
    with patch("agent.agent.run_agent", side_effect=RuntimeError("browser unavailable")):
        record = apply_top_jobs._process_job_browser_agent(
            context,
            job,
            {"candidate": {}, "resume_path": ""},
            [],
        )

    assert record["status"] == "failed"
    assert record["ats"] == "unknown"
    assert record["resume_uploaded"] is False
    assert "browser unavailable" in record["notes"]
