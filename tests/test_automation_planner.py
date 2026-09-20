"""Tests for automation/planner (rule + LLM planners)."""

from __future__ import annotations

import pytest

from agent.types import PageSnapshot
from automation.context import ApplicationContext
from automation.llm_planner import LLMPlanner
from automation.rule_planner import RulePlanner
from automation.types import PlannerDecision, Task, TaskAction, TaskState

from core.models import Job


def snapshot() -> PageSnapshot:
    return PageSnapshot(
        url="https://ats.example.com/apply",
        page_title="Apply",
        domain="ats.example.com",
        page_type="application_form",
    )


def make_task(
    task_id: str,
    question: str,
    action: TaskAction = TaskAction.FILL,
    priority: int = 30,
    required: bool = False,
    dependencies: tuple[str, ...] = (),
) -> Task:
    return Task(
        id=task_id,
        question=question,
        description=question,
        action=action,
        priority=priority,
        required=required,
        dependencies=dependencies,
    )


class TestRulePlanner:
    def test_picks_highest_priority_pending(self) -> None:
        tasks = [
            make_task("task_1", "email", priority=60),
            make_task("task_2", "first_name", priority=30),
        ]
        decision = RulePlanner().select(
            ApplicationContext(), snapshot(), tasks, []
        )
        assert decision.task_id == "task_2"
        assert decision.action == TaskAction.FILL
        assert decision.confidence == 1.0

    def test_skips_done_tasks(self) -> None:
        tasks = [make_task("task_1", "email")]
        decision = RulePlanner().select(
            ApplicationContext(), snapshot(), tasks, ["task_1"]
        )
        assert decision.action == TaskAction.CONTINUE

    def test_skips_answered_tasks(self) -> None:
        context = ApplicationContext()
        context.record_answer("email", "a@b.com")
        tasks = [make_task("task_1", "email")]
        decision = RulePlanner().select(context, snapshot(), tasks, [])
        assert decision.action == TaskAction.CONTINUE

    def test_respects_dependencies(self) -> None:
        tasks = [
            make_task("task_0", "country", action=TaskAction.SELECT, priority=10),
            make_task("task_1", "city", priority=20, dependencies=("task_0",)),
        ]
        context = ApplicationContext()
        decision = RulePlanner().select(context, snapshot(), tasks, [])
        assert decision.task_id == "task_0"
        # after task_0 done, city becomes eligible
        decision2 = RulePlanner().select(
            context, snapshot(), tasks, ["task_0"]
        )
        assert decision2.task_id == "task_1"


class TestLLMPlanner:
    def test_uses_model_decision(self) -> None:
        def model(prompt: str) -> dict:
            return {"task_id": "task_1", "reason": "pick email"}

        tasks = [
            make_task("task_0", "first_name", priority=30),
            make_task("task_1", "email", priority=60),
        ]
        decision = LLMPlanner(model).select(
            ApplicationContext(), snapshot(), tasks, []
        )
        assert decision.task_id == "task_1"
        assert decision.reason == "pick email"

    def test_continue_decision(self) -> None:
        def model(prompt: str) -> dict:
            return {"task_id": "continue", "reason": "done"}

        tasks = [make_task("task_0", "first_name")]
        decision = LLMPlanner(model).select(
            ApplicationContext(), snapshot(), tasks, []
        )
        assert decision.action == TaskAction.CONTINUE

    def test_empty_task_id_falls_back_to_continue(self) -> None:
        def model(prompt: str) -> dict:
            return {"task_id": "", "reason": "none"}

        tasks = [make_task("task_0", "first_name")]
        decision = LLMPlanner(model).select(
            ApplicationContext(), snapshot(), tasks, []
        )
        assert decision.action == TaskAction.CONTINUE

    def test_invalid_json_falls_back_to_rules(self) -> None:
        def model(prompt: str) -> dict:
            raise RuntimeError("model exploded")

        tasks = [
            make_task("task_0", "first_name", priority=30),
            make_task("task_1", "email", priority=60),
        ]
        decision = LLMPlanner(model).select(
            ApplicationContext(), snapshot(), tasks, []
        )
        assert decision.task_id == "task_0"

    def test_unknown_task_id_falls_back_to_rules(self) -> None:
        def model(prompt: str) -> dict:
            return {"task_id": "bogus", "reason": "?"}

        tasks = [make_task("task_0", "first_name")]
        decision = LLMPlanner(model).select(
            ApplicationContext(), snapshot(), tasks, []
        )
        assert decision.task_id == "task_0"

    def test_prompt_contains_tasks(self) -> None:
        seen: dict[str, str] = {}

        def model(prompt: str) -> dict:
            seen["prompt"] = prompt
            return {"task_id": "continue"}

        tasks = [make_task("task_0", "first_name")]
        LLMPlanner(model).select(ApplicationContext(), snapshot(), tasks, [])
        assert "task_0" in seen["prompt"]
        assert "first_name" in seen["prompt"]
