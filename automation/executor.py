"""Task executor — turns a semantic Task into concrete browser actions.

The executor is the translation layer between the automation contracts
and the ``agent`` browser primitives. It never talks to Playwright
directly; it receives an injected :class:`agent.execute.Executor`
(wrapped around a Playwright page) and drives it with
:class:`agent.execute.BrowserCommand` objects.

Flow per task:
    Task -> resolve value (SemanticFieldResolver / context)
         -> map semantic action to a BrowserCommand
         -> delegate to the agent Executor
         -> record the outcome on the ApplicationContext
         -> return an automation.ExecutionResult
"""

from __future__ import annotations

from agent.execute import BrowserAction, BrowserCommand
from agent.execute import Executor as AgentExecutor
from automation.context import ApplicationContext
from automation.resolver import SemanticFieldResolver
from automation.types import ExecutionResult, Task, TaskAction, TaskState


class TaskExecutor:
    """Executes a single semantic task against the browser.

    Attributes:
        agent_executor: The injected ``agent`` executor (wraps Playwright).
        resolver: The injected semantic field resolver.
        context: The application context updated after each action.
    """

    def __init__(
        self,
        agent_executor: AgentExecutor,
        resolver: SemanticFieldResolver,
        context: ApplicationContext,
    ) -> None:
        """Initialize with injected dependencies.

        Args:
            agent_executor: An ``agent`` Executor bound to a live page.
            resolver: Semantic value resolver (from application profile).
            context: Mutable application memory to update.
        """
        self._agent_executor = agent_executor
        self._resolver = resolver
        self._context = context

    # ── Public API ─────────────────────────────────────────────

    def execute(self, task: Task) -> ExecutionResult:
        """Execute a task and update the application context.

        Args:
            task: The semantic task to run.

        Returns:
            The execution outcome as an :class:`ExecutionResult`.
        """
        start = self._now_ms()
        command = self._to_command(task)

        if command is None:
            return ExecutionResult(
                task=task,
                task_state=TaskState.FAILED,
                success=False,
                message=f"Cannot execute action {task.action.value} without a target.",
                duration_ms=0,
            )

        agent_result = self._agent_executor.execute(command)
        duration = self._now_ms() - start

        if not agent_result.success:
            return ExecutionResult(
                task=task,
                task_state=TaskState.FAILED,
                success=False,
                message=agent_result.message,
                duration_ms=duration,
            )

        # Update the context with the answered value.
        self._record_success(task, agent_result.message)
        return ExecutionResult(
            task=task,
            task_state=TaskState.DONE,
            success=True,
            message=agent_result.message,
            answered_field=task.question,
            duration_ms=duration,
        )

    # ── Task -> Command translation ────────────────────────────

    def _to_command(self, task: Task) -> BrowserCommand | None:
        """Map a semantic task to a single BrowserCommand.

        Args:
            task: The semantic task to translate.

        Returns:
            A BrowserCommand, or ``None`` when the task has no target
            (ex. CONTINUE decisions are handled by the engine).
        """
        target = task.field_ref
        action = task.action

        if action == TaskAction.UPLOAD:
            if not target:
                return None
            return BrowserCommand(
                action=BrowserAction.UPLOAD_FILE,
                target=target,
                value=self._resolver.resume_path,
            )

        if action == TaskAction.SELECT:
            if not target:
                return None
            return BrowserCommand(
                action=BrowserAction.SELECT_OPTION,
                target=target,
                value=self._resolve_value(task),
            )

        if action == TaskAction.CHECK:
            if not target:
                return None
            return BrowserCommand(
                action=BrowserAction.CHECK_CHECKBOX,
                target=target,
            )

        if action == TaskAction.FILL:
            if not target:
                return None
            return BrowserCommand(
                action=BrowserAction.FILL_FIELD,
                target=target,
                value=self._resolve_value(task),
            )

        # CONTINUE / REQUEST are orchestrated by the engine, not here.
        return None

    # ── Value resolution ───────────────────────────────────────

    def _resolve_value(self, task: Task) -> str:
        """Return the candidate value for a task.

        The context is consulted first (already-recorded answers win),
        then the semantic resolver (application profile).

        Args:
            task: The task whose question needs a value.

        Returns:
            The value string (may be empty when unknown).
        """
        if task.question and self._context.has_answer(task.question):
            return self._context.reuse_answer(task.question)
        return self._resolver.resolve(task.question)

    # ── Context recording ──────────────────────────────────────

    def _record_success(self, task: Task, message: str) -> None:
        """Record a successful execution on the context.

        Args:
            task: The completed task.
            message: Outcome message (unused; engine owns the timeline).
        """
        if task.question:
            self._context.record_answer(task.question, self._resolve_value(task))
        self._context.mark_task(task.id, TaskState.DONE)
        self._context.record_execution(task.id)

    @staticmethod
    def _now_ms() -> int:
        """Return the current time in milliseconds."""
        import time

        return int(time.perf_counter() * 1000)


__all__ = ["TaskExecutor"]
