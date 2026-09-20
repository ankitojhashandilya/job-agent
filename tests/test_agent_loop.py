"""Behaviour tests for the safety-first browser-agent loop."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent.agent import run_agent
from agent.execute import BrowserAction, ExecutionResult
from agent.types import Button, FormField, PageSnapshot, TaskInfo


def _snapshot(*, fields=None, buttons=None) -> PageSnapshot:
    return PageSnapshot(
        url="https://example.com/application",
        page_title="Application",
        domain="boards.greenhouse.io",
        page_type="application_form",
        fields=fields or [],
        buttons=buttons or [],
    )


def test_agent_advances_known_step_then_stops_before_submit(monkeypatch):
    fill_page = _snapshot(
        fields=[
            FormField(
                id="field:first_name",
                field_type="text",
                label="First Name",
                value="",
                required=True,
            )
        ]
    )
    review_page = _snapshot(
        buttons=[Button(id="button:submit_application", text="Submit application")]
    )
    snapshots = iter([fill_page, review_page, review_page])
    monkeypatch.setattr("agent.agent.observe_page", lambda _: next(snapshots))

    executed = []

    class FakeExecutor:
        def __init__(self, page):
            pass

        def execute(self, command):
            executed.append(command)
            return ExecutionResult(
                success=True,
                action=command.action.value,
                target=command.target,
                message="ok",
                duration_ms=0,
            )

    monkeypatch.setattr("agent.agent.Executor", FakeExecutor)

    result = run_agent(
        MagicMock(),
        TaskInfo(resume_path="", candidate={"first_name": "Test"}),
    )

    assert result.status == "REVIEW_READY_CANDIDATE"
    assert "Final submission blocked" in result.reason
    assert [command.action for command in executed] == [BrowserAction.FILL_FIELD]


def test_agent_hands_unknown_required_question_to_human(monkeypatch):
    snapshot = _snapshot(
        fields=[
            FormField(
                id="field:work_authorization",
                field_type="text",
                label="Work authorization",
                value="",
                required=True,
            )
        ]
    )
    monkeypatch.setattr("agent.agent.observe_page", lambda _: snapshot)

    result = run_agent(MagicMock(), TaskInfo(resume_path="", candidate={}))

    assert result.status == "MANUAL_REQUIRED"
    assert "Required question needs a human answer" in result.reason


def test_agent_executes_submit_only_after_explicit_callback_confirmation(monkeypatch):
    review_page = _snapshot(
        buttons=[Button(id="button:submit_application", text="Submit application")]
    )
    confirmation_page = PageSnapshot(
        url="https://boards.greenhouse.io/acme/confirmation",
        page_title="Application received",
        domain="boards.greenhouse.io",
        page_type="confirmation",
        status_message="Your application has been submitted",
    )
    snapshots = iter([review_page, confirmation_page])
    monkeypatch.setattr("agent.agent.observe_page", lambda _: next(snapshots))

    executed = []

    class FakeExecutor:
        def __init__(self, page):
            pass

        def execute(self, command):
            executed.append(command)
            return ExecutionResult(True, command.action.value, command.target, "ok", 0)

    monkeypatch.setattr("agent.agent.Executor", FakeExecutor)
    result = run_agent(
        MagicMock(),
        TaskInfo(resume_path="", candidate={}),
        submit_approval=lambda _snapshot, _command: True,
    )

    assert result.status == "SUBMISSION_DETECTED"
    assert [command.action for command in executed] == [BrowserAction.CLICK_BUTTON]


def test_external_linkedin_apply_requires_explicit_profile_share_confirmation(monkeypatch):
    job_detail = PageSnapshot(
        url="https://www.linkedin.com/jobs/view/123",
        page_title="Data Engineer | LinkedIn",
        domain="www.linkedin.com",
        page_type="job_details",
        buttons=[Button(id="button:apply", text="Apply")],
    )
    monkeypatch.setattr("agent.agent.observe_page", lambda _: job_detail)

    result = run_agent(MagicMock(), TaskInfo(resume_path="", candidate={}))

    assert result.status == "MANUAL_REQUIRED"
    assert "share your profile" in result.reason
