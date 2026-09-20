"""Simulated end-to-end flows for supported ATS policies."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent.agent import run_agent
from agent.execute import BrowserAction, ExecutionResult
from agent.types import Button, FileInput, FormField, PageSnapshot, TaskInfo


def snapshot(*, fields=None, uploads=None, buttons=None, errors=None, domain="boards.greenhouse.io"):
    return PageSnapshot(
        url=f"https://{domain}/acme/jobs/123/application",
        page_title="Application",
        domain=domain,
        page_type="application_form",
        fields=fields or [],
        file_inputs=uploads or [],
        buttons=buttons or [],
        error_messages=errors or [],
    )


class FakeExecutor:
    def __init__(self, page):
        self.actions = page.actions

    def execute(self, command):
        self.actions.append(command)
        return ExecutionResult(True, command.action.value, command.target, "ok", 0)


def test_supported_flow_fills_uploads_and_never_executes_submit(monkeypatch):
    empty_name = FormField("field:first_name", "text", "First Name", "", required=True)
    filled_name = FormField("field:first_name", "text", "First Name", "Ada", required=True)
    missing_resume = FileInput("upload:resume", "Resume", has_file=False, required=True)
    uploaded_resume = FileInput("upload:resume", "Resume", has_file=True, required=True)
    review = Button("button:submit_application", "Submit Application", button_type="submit")
    observations = iter(
        [
            snapshot(fields=[empty_name]),
            snapshot(fields=[filled_name], uploads=[missing_resume]),
            snapshot(fields=[filled_name], uploads=[missing_resume]),
            snapshot(fields=[filled_name], uploads=[uploaded_resume], buttons=[review]),
            snapshot(fields=[filled_name], uploads=[uploaded_resume], buttons=[review]),
        ]
    )
    monkeypatch.setattr("agent.agent.observe_page", lambda _: next(observations))
    monkeypatch.setattr("agent.agent.Executor", FakeExecutor)
    page = MagicMock()
    page.actions = []

    result = run_agent(page, TaskInfo("resume.pdf", {"first_name": "Ada"}))

    assert result.status == "REVIEW_READY_CANDIDATE"
    assert result.application_form_opened
    assert result.resume_uploaded
    assert [command.action for command in page.actions] == [
        BrowserAction.FILL_FIELD,
        BrowserAction.UPLOAD_FILE,
    ]


def test_validation_error_fails_the_run_after_an_action(monkeypatch):
    before = snapshot(fields=[FormField("field:email", "email", "Email", "", required=True)])
    after = snapshot(
        fields=[FormField("field:email", "email", "Email", "bad", required=True)],
        errors=["Please enter a valid email address"],
    )
    observations = iter([before, after])
    monkeypatch.setattr("agent.agent.observe_page", lambda _: next(observations))
    monkeypatch.setattr("agent.agent.Executor", FakeExecutor)
    page = MagicMock()
    page.actions = []

    result = run_agent(page, TaskInfo("", {"email": "bad"}))

    assert result.status == "FAILED"
    assert "Validation errors" in result.reason


def test_unsupported_ats_becomes_a_human_handoff(monkeypatch):
    monkeypatch.setattr(
        "agent.agent.observe_page",
        lambda _: snapshot(domain="careers.unknown-ats.example"),
    )
    result = run_agent(MagicMock(), TaskInfo("", {}))

    assert result.status == "UNSUPPORTED"
