"""Tests for automation/executor.py and verification.py."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent.execute import BrowserAction, BrowserCommand
from agent.types import FileInput, FormField, PageSnapshot
from agent.verifier import VerificationStatus, Verifier
from automation.context import ApplicationContext
from automation.executor import TaskExecutor
from automation.resolver import SemanticFieldResolver
from automation.types import Task, TaskAction, TaskState
from automation.verification import ApplicationVerifier


@dataclass
class FakeAgentResult:
    success: bool
    message: str = ""
    duration_ms: int = 5


class FakeAgentExecutor:
    """Records BrowserCommands like the real agent Executor."""

    def __init__(self) -> None:
        self.commands: list[BrowserCommand] = []
        self.result = FakeAgentResult(success=True)

    def execute(self, command: BrowserCommand) -> FakeAgentResult:
        self.commands.append(command)
        return self.result


def make_task(
    task_id: str = "task_0",
    question: str = "first_name",
    action: TaskAction = TaskAction.FILL,
    field_ref: str = "field:first_name",
    candidate_key: str = "first_name",
) -> Task:
    return Task(
        id=task_id,
        question=question,
        description=question,
        action=action,
        priority=30,
        field_ref=field_ref,
        candidate_key=candidate_key,
    )


class TestTaskExecutor:
    def test_fill_executes_command(self) -> None:
        agent = FakeAgentExecutor()
        resolver = SemanticFieldResolver(profile={"first_name": "Alice"})
        context = ApplicationContext()
        executor = TaskExecutor(agent, resolver, context)

        result = executor.execute(make_task())

        assert result.success is True
        assert result.task_state == TaskState.DONE
        assert result.answered_field == "first_name"
        assert agent.commands[0].action == BrowserAction.FILL_FIELD
        assert agent.commands[0].target == "field:first_name"
        assert agent.commands[0].value == "Alice"

    def test_records_answer_on_context(self) -> None:
        agent = FakeAgentExecutor()
        resolver = SemanticFieldResolver(profile={"first_name": "Alice"})
        context = ApplicationContext()
        executor = TaskExecutor(agent, resolver, context)

        executor.execute(make_task())

        assert context.has_answer("first_name")
        assert context.reuse_answer("first_name") == "Alice"
        assert context.task_states["task_0"] == TaskState.DONE
        assert context.execution_history == ["task_0"]

    def test_upload_uses_resume_path(self) -> None:
        agent = FakeAgentExecutor()
        resolver = SemanticFieldResolver(resume_path="resume.pdf")
        context = ApplicationContext()
        executor = TaskExecutor(agent, resolver, context)

        task = make_task(question="resume", action=TaskAction.UPLOAD, field_ref="upload:resume")
        result = executor.execute(task)

        assert result.success is True
        command = agent.commands[0]
        assert command.action == BrowserAction.UPLOAD_FILE
        assert command.value == "resume.pdf"

    def test_select_executes_select(self) -> None:
        agent = FakeAgentExecutor()
        resolver = SemanticFieldResolver(profile={"country": "India"})
        context = ApplicationContext()
        executor = TaskExecutor(agent, resolver, context)

        task = make_task(
            question="country",
            action=TaskAction.SELECT,
            field_ref="field:country",
            candidate_key="country",
        )
        executor.execute(task)

        assert agent.commands[0].action == BrowserAction.SELECT_OPTION
        assert agent.commands[0].value == "India"

    def test_check_executes_checkbox(self) -> None:
        agent = FakeAgentExecutor()
        resolver = SemanticFieldResolver(profile={})
        context = ApplicationContext()
        executor = TaskExecutor(agent, resolver, context)

        task = make_task(
            question="authorization",
            action=TaskAction.CHECK,
            field_ref="field:authorization",
        )
        executor.execute(task)

        assert agent.commands[0].action == BrowserAction.CHECK_CHECKBOX

    def test_agent_failure_propagates(self) -> None:
        agent = FakeAgentExecutor()
        agent.result = FakeAgentResult(success=False, message="Field not found")
        resolver = SemanticFieldResolver(profile={"first_name": "Alice"})
        context = ApplicationContext()
        executor = TaskExecutor(agent, resolver, context)

        result = executor.execute(make_task())

        assert result.success is False
        assert result.task_state == TaskState.FAILED
        assert "Field not found" in result.message

    def test_continue_task_has_no_target(self) -> None:
        agent = FakeAgentExecutor()
        resolver = SemanticFieldResolver(profile={})
        context = ApplicationContext()
        executor = TaskExecutor(agent, resolver, context)

        task = make_task(question="", action=TaskAction.CONTINUE, field_ref="")
        result = executor.execute(task)

        assert result.success is False
        assert agent.commands == []

    def test_context_answer_wins_over_profile(self) -> None:
        agent = FakeAgentExecutor()
        resolver = SemanticFieldResolver(profile={"first_name": "Profile"})
        context = ApplicationContext()
        context.record_answer("first_name", "Context")
        executor = TaskExecutor(agent, resolver, context)

        executor.execute(make_task())

        assert agent.commands[0].value == "Context"


def make_snapshot(
    fields: list[FormField] | None = None,
    files: list[FileInput] | None = None,
    page_type: str = "application_form",
    url: str = "https://ats.example.com/apply",
    error_messages: list[str] | None = None,
) -> PageSnapshot:
    return PageSnapshot(
        url=url,
        page_title="Apply",
        domain="ats.example.com",
        page_type=page_type,
        fields=fields or [],
        file_inputs=files or [],
        error_messages=error_messages or [],
    )


def form_field(field_id: str, value: str) -> FormField:
    return FormField(
        id=field_id,
        field_type="text",
        label=field_id,
        value=value,
    )


class TestApplicationVerifier:
    def test_value_persisted(self) -> None:
        verifier = ApplicationVerifier()
        before = make_snapshot(fields=[form_field("field:first_name", "")])
        after = make_snapshot(fields=[form_field("field:first_name", "Alice")])
        report = verifier.verify(before, after)
        assert report.value_persisted is True
        assert report.ok is True

    def test_value_not_persisted(self) -> None:
        verifier = ApplicationVerifier()
        before = make_snapshot(fields=[form_field("field:first_name", "")])
        after = make_snapshot(fields=[form_field("field:first_name", "")])
        report = verifier.verify(before, after)
        assert report.value_persisted is False

    def test_page_advanced_on_url_change(self) -> None:
        verifier = ApplicationVerifier()
        before = make_snapshot(url="https://ats.example.com/apply")
        after = make_snapshot(url="https://ats.example.com/review")
        report = verifier.verify(before, after)
        assert report.page_advanced is True

    def test_page_advanced_on_type_change(self) -> None:
        verifier = ApplicationVerifier()
        before = make_snapshot(page_type="application_form")
        after = make_snapshot(page_type="confirmation")
        report = verifier.verify(before, after)
        assert report.page_advanced is True

    def test_upload_succeeded(self) -> None:
        verifier = ApplicationVerifier()
        before = make_snapshot(
            files=[FileInput(id="upload:resume", label="Resume", has_file=False)]
        )
        after = make_snapshot(
            files=[FileInput(id="upload:resume", label="Resume", has_file=True)]
        )
        report = verifier.verify(before, after, upload_intended=True)
        assert report.upload_succeeded is True

    def test_upload_not_intended(self) -> None:
        verifier = ApplicationVerifier()
        before = make_snapshot(files=[FileInput(id="upload:resume", label="Resume", has_file=False)])
        after = make_snapshot(files=[FileInput(id="upload:resume", label="Resume", has_file=True)])
        report = verifier.verify(before, after, upload_intended=False)
        assert report.upload_succeeded is False

    def test_new_questions_appeared(self) -> None:
        verifier = ApplicationVerifier()
        before = make_snapshot(fields=[form_field("field:first_name", "")])
        after = make_snapshot(
            fields=[
                form_field("field:first_name", "Alice"),
                form_field("field:last_name", ""),
            ]
        )
        report = verifier.verify(before, after)
        assert report.new_questions_appeared is True
        assert report.should_replan is True

    def test_validation_failed(self) -> None:
        verifier = ApplicationVerifier()
        before = make_snapshot()
        after = make_snapshot(
            page_type="application_form",
            error_messages=["This field is required"],
        )
        report = verifier.verify(before, after)
        assert report.validation_failed is True
        assert report.ok is False

    def test_status_success(self) -> None:
        verifier = ApplicationVerifier()
        snapshot = make_snapshot(page_type="confirmation")
        assert Verifier.verify(snapshot) == VerificationStatus.SUCCESS
