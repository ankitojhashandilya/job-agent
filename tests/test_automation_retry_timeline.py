"""Tests for automation/retry.py and timeline.py."""

from __future__ import annotations

import json

from automation.context import ApplicationContext
from automation.retry import RetryEngine
from automation.timeline import Timeline
from automation.types import Task, TaskAction, TaskState, VerificationReport


def make_task(task_id: str = "task_0", question: str = "email") -> Task:
    return Task(
        id=task_id,
        question=question,
        description=question,
        action=TaskAction.FILL,
        required=True,
    )


class TestRetryEngine:
    def test_should_retry_within_budget(self) -> None:
        engine = RetryEngine(max_retries=3)
        context = ApplicationContext()
        assert engine.should_retry(context, make_task(), attempts=1) is True

    def test_stops_after_max_retries(self) -> None:
        engine = RetryEngine(max_retries=2)
        context = ApplicationContext()
        context.retry_count = 2
        assert engine.should_retry(context, make_task(), attempts=1) is False

    def test_stops_after_max_attempts(self) -> None:
        engine = RetryEngine(max_attempts_per_round=3)
        context = ApplicationContext()
        assert engine.should_retry(context, make_task(), attempts=3) is False

    def test_stops_when_task_done(self) -> None:
        engine = RetryEngine()
        context = ApplicationContext()
        context.mark_task("task_0", TaskState.DONE)
        assert engine.should_retry(context, make_task(), attempts=1) is False

    def test_retry_increments_counter_and_warns(self) -> None:
        engine = RetryEngine()
        context = ApplicationContext()
        task = make_task()
        state = engine.retry(context, task, context.snapshot(), attempts=1)
        assert state == TaskState.IN_PROGRESS
        assert context.retry_count == 1
        assert any("retry" in w for w in context.warnings)

    def test_retry_exhausts_to_unknown(self) -> None:
        engine = RetryEngine(max_retries=1)
        context = ApplicationContext()
        task = make_task()
        state = engine.retry(context, task, context.snapshot(), attempts=1)
        assert state == TaskState.UNKNOWN
        assert context.unknown_questions == ["email"]

    def test_verify_after_retry_persisted(self) -> None:
        engine = RetryEngine()
        context = ApplicationContext()
        task = make_task()
        state = engine.verify_after_retry(
            context, task, VerificationReport(value_persisted=True)
        )
        assert state == TaskState.DONE

    def test_verify_after_retry_page_advanced(self) -> None:
        engine = RetryEngine()
        context = ApplicationContext()
        task = make_task()
        state = engine.verify_after_retry(
            context, task, VerificationReport(page_advanced=True)
        )
        assert state == TaskState.SKIPPED

    def test_verify_after_retry_validation_failed(self) -> None:
        engine = RetryEngine()
        context = ApplicationContext()
        task = make_task()
        state = engine.verify_after_retry(
            context, task, VerificationReport(validation_failed=True)
        )
        assert state == TaskState.FAILED

    def test_verify_after_retry_required_unknown(self) -> None:
        engine = RetryEngine()
        context = ApplicationContext()
        task = make_task(question="salary")
        state = engine.verify_after_retry(
            context, task, VerificationReport()
        )
        assert state == TaskState.UNKNOWN

    def test_verify_after_retry_optional_skipped(self) -> None:
        engine = RetryEngine()
        context = ApplicationContext()
        task = make_task(question="linkedin_url")
        task = Task(
            id=task.id,
            question=task.question,
            description=task.description,
            action=task.action,
            required=False,
        )
        state = engine.verify_after_retry(context, task, VerificationReport())
        assert state == TaskState.SKIPPED


class TestTimeline:
    def test_record_assigns_sequence(self) -> None:
        timeline = Timeline()
        first = timeline.record("Observe Page", "page=form")
        second = timeline.record("Filled", "first_name")
        assert first.sequence == 1
        assert second.sequence == 2
        assert len(timeline.events) == 2

    def test_to_dicts(self) -> None:
        timeline = Timeline()
        timeline.record("Observe Page", "page=form", timestamp="2026-01-01T00:00:00+00:00")
        data = timeline.to_dicts()
        assert data[0]["event"] == "Observe Page"
        assert data[0]["sequence"] == 1

    def test_write_creates_json(self, tmp_path) -> None:
        timeline = Timeline()
        timeline.record("Completed", "done", timestamp="2026-01-01T00:00:00+00:00")
        destination = tmp_path / "timeline.json"
        timeline.write(destination)
        payload = json.loads(destination.read_text(encoding="utf-8"))
        assert payload["total"] == 1
        assert payload["events"][0]["event"] == "Completed"

    def test_extend_preserves_order(self) -> None:
        timeline = Timeline()
        timeline.record("A", timestamp="t0")
        from automation.types import TimelineEvent

        timeline.extend(
            [
                TimelineEvent(sequence=99, event_type="B", timestamp="t1"),
                TimelineEvent(sequence=99, event_type="C", timestamp="t2"),
            ]
        )
        assert [e.event_type for e in timeline.events] == ["A", "B", "C"]
        assert [e.sequence for e in timeline.events] == [1, 2, 3]
