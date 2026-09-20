"""LLM planner — selects the next task using an injected model callable.

The LLM planner never touches Playwright and never imports the browser.
It receives a callable (``ModelCall``) in its constructor — typically
wired to ``ollama_client.generate_json`` in the engine factory — and
asks it to choose among the remaining tasks.

Design:
- The model callable must return a JSON dict with a ``task_id`` (or
  ``"continue"``) key.
- On failure/exception the planner falls back to the deterministic
  :class:`RulePlanner` decision so the loop never hard-fails.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from agent.types import PageSnapshot
from automation.context import ApplicationContext
from automation.planner import Planner
from automation.rule_planner import RulePlanner
from automation.types import PlannerDecision, Task, TaskAction

# A JSON-returning model callable (ex. ollama_client.generate_json).
ModelCall = Callable[[str], dict[str, Any]]


class LLMPlanner:
    """LLM-driven task selection with rule fallback.

    Attributes:
        model: Injected JSON-returning callable.
        fallback: The deterministic planner used on model failure.
        max_candidates: Number of remaining tasks to expose to the model.
    """

    def __init__(
        self,
        model: ModelCall,
        fallback: Planner | None = None,
        max_candidates: int = 8,
    ) -> None:
        """Initialize with dependency injection.

        Args:
            model: A callable returning a JSON dict from a prompt.
            fallback: Fallback planner (defaults to :class:`RulePlanner`).
            max_candidates: Cap on tasks listed in the prompt.
        """
        self._model = model
        self._fallback = fallback or RulePlanner()
        self._max_candidates = max_candidates

    def select(
        self,
        context: ApplicationContext,
        snapshot: PageSnapshot,
        tasks: list[Task],
        history: list[str],
    ) -> PlannerDecision:
        """Select the next task via the LLM, falling back to rules.

        Args:
            context: Mutable application memory.
            snapshot: Current page observation.
            tasks: Extracted tasks for the current page.
            history: Ordered ids of tasks already executed.

        Returns:
            A :class:`PlannerDecision`.
        """
        try:
            prompt = self._build_prompt(context, snapshot, tasks, history)
            raw = self._model(prompt)
            return self._parse(raw, snapshot, tasks, context, history)
        except Exception:
            return self._fallback.select(context, snapshot, tasks, history)

    # ── Prompt / parse ────────────────────────────────────────

    def _build_prompt(
        self,
        context: ApplicationContext,
        snapshot: PageSnapshot,
        tasks: list[Task],
        history: list[str],
    ) -> str:
        """Build a compact, token-efficient JSON prompt.

        Args:
            context: Application memory.
            snapshot: Current page observation.
            tasks: Candidate tasks.
            history: Executed task ids.

        Returns:
            A prompt asking the model to choose the next task id.
        """
        remaining = [
            task
            for task in tasks
            if task.id not in set(history)
            and not context.has_answer(task.question)
        ][: self._max_candidates]

        payload = {
            "page_type": snapshot.page_type,
            "domain": snapshot.domain,
            "url": snapshot.url,
            "questions": [
                {
                    "id": task.id,
                    "question": task.question,
                    "description": task.description,
                    "action": task.action.value,
                    "priority": task.priority,
                    "required": task.required,
                }
                for task in remaining
            ],
            "answered": list(context.answered_fields),
            "history": history,
            "instructions": (
                "Select the single next task to execute. Respond with JSON: "
                '{"task_id": "<task id or continue>", "reason": "..."}'
            ),
        }
        return json.dumps(payload, indent=2)

    def _parse(
        self,
        raw: dict[str, Any],
        snapshot: PageSnapshot,
        tasks: list[Task],
        context: ApplicationContext,
        history: list[str],
    ) -> PlannerDecision:
        """Interpret the model JSON into a PlannerDecision.

        Args:
            raw: The model's JSON response.
            snapshot: Current page observation.
            tasks: Candidate tasks.
            context: Application memory.
            history: Executed task ids.

        Returns:
            The decision, or a rule fallback if the response is invalid.
        """
        if not isinstance(raw, dict):
            return self._rule_fallback(snapshot, context, tasks, history)

        task_id = str(raw.get("task_id") or "").strip()
        reason = str(raw.get("reason") or "LLM chose.")

        if not task_id or task_id == "continue":
            return PlannerDecision(
                task_id="",
                action=TaskAction.CONTINUE,
                reason=reason,
                confidence=0.5,
            )

        for task in tasks:
            if task.id == task_id:
                return PlannerDecision(
                    task_id=task.id,
                    action=task.action,
                    reason=reason,
                    confidence=0.6,
                )

        # Unknown task id → fall back to rules.
        return self._rule_fallback(snapshot, context, tasks, history)

    def _rule_fallback(
        self,
        snapshot: PageSnapshot,
        context: ApplicationContext,
        tasks: list[Task],
        history: list[str],
    ) -> PlannerDecision:
        """Delegate to the deterministic planner.

        Args:
            snapshot: Current page observation.
            context: Application memory.
            tasks: Candidate tasks.
            history: Executed task ids.

        Returns:
            The rule planner's decision.
        """
        return self._fallback.select(context, snapshot, tasks, history)


__all__ = ["LLMPlanner", "ModelCall"]
