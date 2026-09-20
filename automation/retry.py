"""Retry policy — the retry ladder for a failing task.

When a task's execution or verification fails, the retry engine walks a
defined ladder before giving up:

    1. Re-observe the page and re-extract questions/tasks.
    2. Retry the same task once.
    3. Ask the LLM planner for a fresh decision.
    4. Scroll the field into view and retry.
    5. Capture a screenshot (for debugging) and retry.
    6. Mark the task unknown.
    7. Continue if optional; abandon the run only if the task is required.

The ladder is pure and injected — it never touches Playwright.
"""

from __future__ import annotations

from agent.types import PageSnapshot
from automation.context import ApplicationContext
from automation.types import Task, TaskState, VerificationReport


class RetryEngine:
    """Walks the retry ladder for a task.

    Attributes:
        max_retries: Maximum retries per task before marking unknown.
        max_attempts_per_round: Hard cap on ladder rounds per task.
    """

    def __init__(
        self,
        max_retries: int = 3,
        max_attempts_per_round: int = 6,
    ) -> None:
        """Initialize the retry policy.

        Args:
            max_retries: Retry budget per task.
            max_attempts_per_round: Hard cap on attempts per round.
        """
        self._max_retries = max_retries
        self._max_attempts_per_round = max_attempts_per_round

    def should_retry(
        self,
        context: ApplicationContext,
        task: Task,
        attempts: int,
    ) -> bool:
        """Return whether the engine should retry the task.

        Args:
            context: Application memory (retry counters live here).
            task: The failing task.
            attempts: Number of attempts already made for this task.

        Returns:
            ``True`` while within budget and the task is still pending.
        """
        if context.retry_count >= self._max_retries:
            return False
        if attempts >= self._max_attempts_per_round:
            return False
        state = context.task_states.get(task.id, TaskState.PENDING)
        return state == TaskState.PENDING or state == TaskState.IN_PROGRESS

    def retry(
        self,
        context: ApplicationContext,
        task: Task,
        snapshot: PageSnapshot,
        attempts: int,
    ) -> TaskState:
        """Advance the task state after a failed attempt.

        Args:
            context: Application memory to update.
            task: The failing task.
            snapshot: Latest page snapshot.
            attempts: Number of attempts already made for this task.

        Returns:
            The new task state after applying retry policy.
        """
        context.retry_count += 1
        context.record_warning(
            f"retry[{attempts}] task={task.id} desc={task.description}"
        )

        if attempts >= self._max_attempts_per_round:
            return self._mark_unknown(context, task)
        if context.retry_count >= self._max_retries:
            return self._mark_unknown(context, task)

        return TaskState.IN_PROGRESS

    def verify_after_retry(
        self,
        context: ApplicationContext,
        task: Task,
        report: VerificationReport,
    ) -> TaskState:
        """Finalize a task state from a verification report.

        Args:
            context: Application memory to update.
            task: The task being finalized.
            report: The verification report for the retried action.

        Returns:
            The final task state.
        """
        if report.value_persisted or report.upload_succeeded:
            context.mark_task(task.id, TaskState.DONE)
            return TaskState.DONE
        if report.page_advanced:
            context.mark_task(task.id, TaskState.SKIPPED)
            return TaskState.SKIPPED
        if not report.ok:
            context.mark_task(task.id, TaskState.FAILED)
            return TaskState.FAILED
        if task.required:
            context.mark_task(task.id, TaskState.UNKNOWN)
            return TaskState.UNKNOWN
        context.mark_task(task.id, TaskState.SKIPPED)
        return TaskState.SKIPPED

    @staticmethod
    def _mark_unknown(context: ApplicationContext, task: Task) -> TaskState:
        """Mark a task unknown and record the unresolved question."""
        context.mark_task(task.id, TaskState.UNKNOWN)
        context.record_unknown(task.question, task.description)
        return TaskState.UNKNOWN


__all__ = ["RetryEngine"]
