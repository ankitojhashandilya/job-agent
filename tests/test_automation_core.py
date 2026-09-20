"""Tests for automation/contracts (types.py) and context.py."""

from __future__ import annotations

import pytest

from automation.context import ApplicationContext
from automation.types import (
    ApplicationResult,
    ExecutionResult,
    PlannerDecision,
    Question,
    QuestionType,
    Task,
    TaskAction,
    TaskState,
    TimelineEvent,
    VerificationReport,
)
from core.models import Job


def make_job() -> Job:
    return Job(
        source_job_id="job_1",
        url="https://ats.example.com/jobs/1",
        company="Acme",
    )


class TestQuestion:
    def test_frozen_immutable(self) -> None:
        question = Question(
            id="first_name",
            question_type=QuestionType.TEXT,
            raw_label="First name",
        )
        with pytest.raises(AttributeError):
            question.id = "last_name"  # type: ignore[misc]

    def test_defaults(self) -> None:
        question = Question(
            id="email",
            question_type=QuestionType.EMAIL,
            raw_label="Email",
        )
        assert question.label_source == "label"
        assert question.confidence == 1.0
        assert question.required is False
        assert question.field_ref == ""


class TestTask:
    def test_frozen_immutable(self) -> None:
        task = Task(
            id="task_1",
            description="Fill First name",
            action=TaskAction.FILL,
            question="first_name",
        )
        with pytest.raises(AttributeError):
            task.description = "other"  # type: ignore[misc]

    def test_defaults(self) -> None:
        task = Task(
            id="task_1",
            description="Fill First name",
            action=TaskAction.FILL,
        )
        assert task.question == ""
        assert task.priority == 100
        assert task.required is False
        assert task.dependencies == ()
        assert task.field_ref == ""
        assert task.candidate_key == ""


class TestPlannerDecision:
    def test_continue_decision(self) -> None:
        decision = PlannerDecision(
            task_id="",
            action=TaskAction.CONTINUE,
            reason="No tasks left.",
        )
        assert decision.confidence == 1.0
        assert decision.action == TaskAction.CONTINUE


class TestExecutionResult:
    def test_defaults(self) -> None:
        task = Task(
            id="task_1",
            description="Fill Email",
            action=TaskAction.FILL,
            question="email",
        )
        result = ExecutionResult(
            task=task,
            task_state=TaskState.DONE,
            success=True,
            message="ok",
        )
        assert result.answered_field == ""
        assert result.duration_ms == 0
        assert result.warnings == ()


class TestVerificationReport:
    def test_ok_when_clean(self) -> None:
        report = VerificationReport(value_persisted=True)
        assert report.ok is True

    def test_not_ok_when_validation_failed(self) -> None:
        report = VerificationReport(validation_failed=True)
        assert report.ok is False

    def test_not_ok_when_ats_rejected(self) -> None:
        report = VerificationReport(ats_rejected=True)
        assert report.ok is False


class TestTimelineEvent:
    def test_to_dict(self) -> None:
        event = TimelineEvent(
            sequence=1,
            event_type="Observe Page",
            timestamp="2026-01-01T00:00:00+00:00",
            detail="page=application_form",
        )
        assert event.to_dict() == {
            "sequence": 1,
            "event": "Observe Page",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "detail": "page=application_form",
        }


class TestApplicationResult:
    def test_defaults(self) -> None:
        context = ApplicationContext()
        result = ApplicationResult(status="completed", context=context)
        assert result.iterations == 0
        assert result.timeline == ()
        assert result.last_event == ""
        assert result.error == ""


class TestApplicationContext:
    def test_for_job_seeds_identity(self) -> None:
        job = make_job()
        context = ApplicationContext.for_job(job)
        assert context.job_id == "job_1"
        assert context.job_url == "https://ats.example.com/jobs/1"
        assert context.company == "Acme"
        assert "started" in context.timestamps

    def test_for_job_seeds_profile_answers(self) -> None:
        job = make_job()
        profile = {
            "candidate": {
                "first_name": "Alice",
                "last_name": "",
                "email": "alice@example.com",
            }
        }
        context = ApplicationContext.for_job(job, profile=profile)
        assert context.answers["first_name"] == "Alice"
        assert context.answers["email"] == "alice@example.com"
        assert "last_name" not in context.answers

    def test_record_answer_and_reuse(self) -> None:
        context = ApplicationContext()
        context.record_answer("email", "a@b.com")
        assert context.has_answer("email")
        assert context.reuse_answer("email") == "a@b.com"
        assert "email" in context.answered_fields

    def test_record_answer_dedupes_fields(self) -> None:
        context = ApplicationContext()
        context.record_answer("email", "a@b.com")
        context.record_answer("email", "c@d.com")
        assert context.answered_fields == ["email"]
        assert context.reuse_answer("email") == "c@d.com"

    def test_record_upload(self) -> None:
        context = ApplicationContext()
        context.record_upload("resume.pdf", kind="resume")
        assert context.resume_uploaded is True
        assert context.uploaded_files == ["resume.pdf"]

    def test_record_error_bumps_retry(self) -> None:
        context = ApplicationContext()
        context.record_error("boom")
        assert context.last_error == "boom"
        assert context.retry_count == 1

    def test_record_unknown_and_warning(self) -> None:
        context = ApplicationContext()
        context.record_unknown("salary", "Salary not in profile")
        assert context.unknown_questions == ["salary"]
        assert any("salary" in w for w in context.warnings)

    def test_mark_task_and_history(self) -> None:
        context = ApplicationContext()
        context.mark_task("task_1", TaskState.DONE)
        context.record_execution("task_1")
        assert context.task_states["task_1"] == TaskState.DONE
        assert context.execution_history == ["task_1"]

    def test_completion_percentage(self) -> None:
        context = ApplicationContext()
        context.tasks = {
            "task_1": Task(
                id="task_1",
                description="Email",
                action=TaskAction.FILL,
                question="email",
            ),
            "task_2": Task(
                id="task_2",
                description="Phone",
                action=TaskAction.FILL,
                question="phone",
            ),
        }
        assert context.completion_percentage == 0.0
        context.record_answer("email", "a@b.com")
        assert context.completion_percentage == 50.0

    def test_snapshot_serializable(self) -> None:
        context = ApplicationContext()
        context.record_answer("email", "a@b.com")
        data = context.snapshot()
        assert data["answers"] == {"email": "a@b.com"}
        assert data["job_id"] == ""
