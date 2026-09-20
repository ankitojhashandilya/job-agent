"""Planner interface — the strategy seam for task selection.

Both the deterministic rule planner (fallback) and the LLM planner
implement this protocol. The planner receives the application context,
the current page snapshot, the extracted task list, and recent execution
history, and decides which task should execute next.
"""

from __future__ import annotations

from typing import Protocol

from agent.types import PageSnapshot
from automation.context import ApplicationContext
from automation.types import PlannerDecision, Task


class Planner(Protocol):
    """Strategy interface for deciding the next task.

    Implementations must return a :class:`PlannerDecision`. Returning
    ``None`` is not allowed — a planner always decides something; the
    engine interprets decisions whose task is already done as "advance".
    """

    def select(
        self,
        context: ApplicationContext,
        snapshot: PageSnapshot,
        tasks: list[Task],
        history: list[str],
    ) -> PlannerDecision:
        """Select the next task to execute.

        Args:
            context: Mutable application memory.
            snapshot: Current page observation.
            tasks: Extracted tasks for the current page.
            history: Ordered ids of tasks already executed.

        Returns:
            The next :class:`PlannerDecision`.
        """
        ...
