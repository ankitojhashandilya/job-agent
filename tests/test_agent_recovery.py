"""Production loop progress limits and longer forms, independent of a browser."""

from unittest.mock import MagicMock

from agent.agent import run_agent
from agent.execute import BrowserAction, ExecutionResult
from agent.types import Button, FormField, PageSnapshot, TaskInfo


def test_more_than_fifteen_fields_complete_without_exhausting_the_budget(monkeypatch):
    values = [""] * 20

    def observe(_):
        return PageSnapshot(
            "https://boards.greenhouse.io/acme/jobs/1",
            "Application",
            "boards.greenhouse.io",
            "application_form",
            fields=[
                FormField(f"field:email_{i}", "email", "Email", value, required=True)
                for i, value in enumerate(values)
            ],
            buttons=[Button("button:submit_application", "Submit application")],
        )

    class Executor:
        def __init__(self, _):
            pass

        def execute(self, command):
            assert command.action == BrowserAction.FILL_FIELD
            values[int(command.target.rsplit("_", 1)[1])] = command.value
            return ExecutionResult(True, command.action.value, command.target, "ok", 0)

    monkeypatch.setattr("agent.agent.observe_page", observe)
    monkeypatch.setattr("agent.agent.Executor", Executor)
    monkeypatch.setattr("agent.agent.time.sleep", lambda _: None)
    result = run_agent(MagicMock(), TaskInfo("", {"email": "ada@example.test"}))
    assert result.status == "REVIEW_READY_CANDIDATE"
    assert result.iterations == 21
    assert len(result.fields_filled) == 20


def test_duplicate_linkedin_apply_still_requires_profile_share_confirmation(monkeypatch):
    snapshot = PageSnapshot(
        "https://www.linkedin.com/jobs/view/123/",
        "Job",
        "www.linkedin.com",
        "job_details",
        buttons=[
            Button("button:apply", "Apply", enabled=False, interactable=False),
            Button("button:apply_2", "Apply"),
        ],
    )
    monkeypatch.setattr("agent.agent.observe_page", lambda _: snapshot)
    result = run_agent(MagicMock(), TaskInfo("", {}))
    assert result.status == "MANUAL_REQUIRED"
    assert "share your profile" in result.reason
