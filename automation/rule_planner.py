"""Deterministic rule-based planner (the fallback strategy).

Implements the :class:`automation.planner.Planner` protocol without any
LLM. Rules, in order:

1. If every task is complete or already answered in context → CONTINUE.
2. Otherwise pick the highest-priority task that is not yet done, is not
   already answered, and whose dependencies are satisfied.
3. If no actionable task exists but there are unanswered optional tasks
   → pick the first unresolved one.
"""

from __future__ import annotations

from agent.types import PageSnapshot
from automation.context import ApplicationContext
from automation.types import PlannerDecision, Task, TaskAction


class RulePlanner:
    """Deterministic fallback planner."""

    def select(
        self,
        context: ApplicationContext,
        snapshot: PageSnapshot,
        tasks: list[Task],
        history: list[str],
    ) -> PlannerDecision:
        """Select the next task using deterministic priority rules.

        Args:
            context: Mutable application memory (answers/done set).
            snapshot: Current page observation.
            tasks: Extracted tasks for the current page.
            history: Ordered ids of tasks already executed.

        Returns:
            The next task to run, or a CONTINUE decision when nothing
            remains.
        """
        done_ids = set(history)

        candidates = [
            task
            for task in tasks
            if task.id not in done_ids
            and not context.has_answer(task.question)
            and all(dep in done_ids for dep in task.dependencies)
        ]
        if not candidates:
            return PlannerDecision(
                task_id="",
                action=TaskAction.CONTINUE,
                reason="No unresolved actionable task.",
                confidence=1.0,
            )

        candidates.sort(key=lambda task: (task.priority, task.id))
        chosen = candidates[0]
        return PlannerDecision(
            task_id=chosen.id,
            action=chosen.action,
            reason=f"Rule planner chose {chosen.description}.",
            confidence=1.0,
        )


__all__ = ["RulePlanner"]
