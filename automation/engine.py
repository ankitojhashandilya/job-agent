"""ApplicationEngine — the orchestrator loop for Browser Agent V2.

The engine composes the pipeline and owns the control flow:

    observe -> understand (questions) -> extract tasks -> plan
    -> execute -> verify -> retry (ladder) -> continue

It holds no Playwright logic itself; every browser interaction is
delegated to the injected ``agent`` primitives (via the TaskExecutor
and an advance callback). All cross-module communication uses the
canonical contracts.

The engine is deliberately ATS-agnostic. ATS adapters plug into the
``advance`` seam and the ``page_type`` classifier — they are NOT
implemented yet (see repository rules).
"""

from __future__ import annotations

from collections.abc import Callable

from agent.execute import BrowserAction, BrowserCommand
from agent.execute import Executor as AgentExecutor
from agent.types import PageSnapshot
from agent.verifier import VerificationStatus, Verifier
from automation.context import ApplicationContext
from automation.executor import TaskExecutor
from automation.planner import Planner
from automation.questions import understand_page
from automation.retry import RetryEngine
from automation.tasks import extract_tasks
from automation.timeline import (
    EVENT_CLICK,
    EVENT_COMPLETE,
    EVENT_EXTRACT,
    EVENT_OBSERVE,
    EVENT_RESOLVE,
    EVENT_RETRY,
    EVENT_VERIFY,
    Timeline,
)
from automation.types import (
    ApplicationResult,
    ExecutionResult,
    Task,
    TaskAction,
    TaskState,
)
from automation.verification import ApplicationVerifier

# Callables injected into the engine.
Observer = Callable[[], PageSnapshot]
Advance = Callable[[PageSnapshot], PageSnapshot]
Scroll = Callable[[PageSnapshot, Task], bool]
Screenshot = Callable[[str], str]

# Text used to identify the "advance" button.
_ADVANCE_KEYWORDS = (
    "continue",
    "submit",
    "next",
    "save and continue",
    "review",
    "apply now",
    "done",
)


class ApplicationEngine:
    """Composes and runs the application pipeline once.

    Attributes:
        context: The mutable application memory.
        timeline: The event recorder.
        observer: Callable returning the current PageSnapshot.
        planner: The injected planner strategy.
        executor: The injected TaskExecutor.
        verifier: The injected ApplicationVerifier.
        retry: The injected RetryEngine.
        advance: Callable that clicks the continue button and re-observes.
        max_iterations: Cap on loop iterations before abort.
    """

    def __init__(
        self,
        context: ApplicationContext,
        timeline: Timeline,
        observer: Observer,
        planner: Planner,
        executor: TaskExecutor,
        verifier: ApplicationVerifier,
        retry: RetryEngine,
        advance: Advance,
        scroll: Scroll | None = None,
        screenshot: Screenshot | None = None,
        max_iterations: int = 30,
    ) -> None:
        """Initialize the engine with injected dependencies.

        Args:
            context: Application memory (pre-seeded via ``for_job``).
            timeline: Event recorder.
            observer: Callable returning the current snapshot.
            planner: Task-selection strategy.
            executor: Semantic TaskExecutor.
            verifier: Post-action verification.
            retry: Retry ladder policy.
            advance: Callable to click continue and re-observe.
            scroll: Optional callable to scroll a field into view.
            screenshot: Optional callable to capture a debug screenshot.
            max_iterations: Loop cap before aborting.
        """
        self.context = context
        self.timeline = timeline
        self.observer = observer
        self.planner = planner
        self.executor = executor
        self.verifier = verifier
        self.retry = retry
        self.advance = advance
        self.scroll = scroll or self._default_scroll
        self.screenshot = screenshot or self._default_screenshot
        self.max_iterations = max_iterations

    # ── Run ────────────────────────────────────────────────────

    def run(self) -> ApplicationResult:
        """Run the application pipeline.

        Returns:
            The final :class:`ApplicationResult` for this run.
        """
        snapshot = self.observer()
        self.timeline.record(
            EVENT_OBSERVE, f"page={snapshot.page_type} url={snapshot.url}"
        )

        questions = understand_page(snapshot)
        tasks = extract_tasks(questions)
        self.context.tasks = {task.id: task for task in tasks}
        self.timeline.record(EVENT_EXTRACT, f"tasks={len(tasks)}")

        iterations = 0
        while iterations < self.max_iterations:
            iterations += 1

            history = self._history()
            decision = self.planner.select(
                self.context, snapshot, list(tasks), history
            )

            if decision.action == TaskAction.CONTINUE:
                status = Verifier.verify(snapshot)
                if status == VerificationStatus.SUCCESS:
                    self.timeline.record(EVENT_COMPLETE, "Application submitted")
                    return self._result("completed", snapshot, iterations)
                if status in (
                    VerificationStatus.ACCOUNT_REQUIRED,
                    VerificationStatus.FAILED,
                ):
                    self.context.record_warning(f"verifier status={status.value}")
                    return self._result("blocked", snapshot, iterations)

                snapshot = self._advance_and_reobserve(snapshot)
                continue

            task = self._find_task(tasks, decision.task_id)
            if task is None:
                snapshot = self._advance_and_reobserve(snapshot)
                continue

            self.timeline.record(EVENT_RESOLVE, task.description)
            before = snapshot
            result = self.executor.execute(task)
            after = self.observer()
            context_state = self._finalize_task(task, result, before)

            if context_state in (TaskState.DONE, TaskState.SKIPPED):
                if task.question and context_state == TaskState.DONE:
                    self.context.mark_task(task.id, TaskState.DONE)
                report = self.verifier.verify(
                    before,
                    after,
                    upload_intended=(task.action == TaskAction.UPLOAD),
                )
                self.timeline.record(EVENT_VERIFY, report.note)
                snapshot = after

                if report.page_advanced or report.new_questions_appeared:
                    snapshot = self._replan(snapshot)
                elif report.validation_failed or not report.ok:
                    self.context.record_warning(f"verification: {report.note}")
                continue

            # Task failed → retry ladder.
            snapshot = self._retry_ladder(task, tasks, after, iterations)

        return self._result("aborted", snapshot, iterations)

    # ── Internal orchestration ─────────────────────────────────

    def _retry_ladder(
        self,
        task: Task,
        tasks: list[Task],
        snapshot: PageSnapshot,
        attempts: int,
    ) -> PageSnapshot:
        """Walk the retry ladder for a failing task.

        Args:
            task: The failing task.
            tasks: The current task list.
            snapshot: The latest page snapshot.
            attempts: Attempt counter for this task.

        Returns:
            The latest page snapshot after retries.
        """
        while self.retry.should_retry(self.context, task, attempts):
            self.timeline.record(EVENT_RETRY, task.description)
            attempts += 1
            snapshot = self.observer()

            state = self.retry.retry(self.context, task, snapshot, attempts)
            if state != TaskState.IN_PROGRESS:
                break

            if self.scroll(snapshot, task):
                result = self.executor.execute(task)
                if result.success:
                    return self._replan(snapshot)

            # Ask the planner for a fresh decision.
            history = self._history()
            decision = self.planner.select(self.context, snapshot, tasks, history)
            if decision.action == TaskAction.CONTINUE:
                return self._advance_and_reobserve(snapshot)

        self.context.record_unknown(task.question, task.description)
        self.context.mark_task(task.id, TaskState.UNKNOWN)
        return snapshot

    def _finalize_task(
        self,
        task: Task,
        result: ExecutionResult,
        before: PageSnapshot,
    ) -> TaskState:
        """Record the outcome of a task execution on the context.

        Args:
            task: The executed task.
            result: The execution result.
            before: Snapshot captured before the action ran.

        Returns:
            ``DONE`` on success, otherwise the task is marked unknown
            and ``UNKNOWN`` is returned so the engine enters the retry
            ladder.
        """
        if result.success:
            return TaskState.DONE
        self.retry.verify_after_retry(
            self.context,
            task,
            self.verifier.verify(
                before,
                self.observer(),
                upload_intended=(task.action == TaskAction.UPLOAD),
            ),
        )
        return TaskState.UNKNOWN

    def _advance_and_reobserve(self, snapshot: PageSnapshot) -> PageSnapshot:
        """Click continue and return the new page snapshot.

        Args:
            snapshot: The pre-advance snapshot.

        Returns:
            The snapshot after advancing.
        """
        self.timeline.record(EVENT_CLICK, "advance")
        return self.advance(snapshot)

    def _replan(self, snapshot: PageSnapshot) -> PageSnapshot:
        """Re-observe and re-extract tasks after the page changed.

        Args:
            snapshot: The current snapshot.

        Returns:
            The refreshed snapshot with tasks re-extracted.
        """
        snapshot = self.observer()
        questions = understand_page(snapshot)
        tasks = extract_tasks(questions)
        self.context.tasks = {task.id: task for task in tasks}
        self.timeline.record(EVENT_EXTRACT, f"tasks={len(tasks)}")
        return snapshot

    def _find_task(self, tasks: list[Task], task_id: str) -> Task | None:
        """Look up a task by id.

        Args:
            tasks: The task list.
            task_id: The target task id.

        Returns:
            The matching task, or ``None``.
        """
        for task in tasks:
            if task.id == task_id:
                return task
        return None

    def _history(self) -> list[str]:
        """Return the ordered list of executed task ids."""
        return list(self.context.execution_history)

    def _result(
        self,
        status: str,
        snapshot: PageSnapshot,
        iterations: int,
    ) -> ApplicationResult:
        """Build the final ApplicationResult.

        Args:
            status: Final status string.
            snapshot: Final page snapshot.
            iterations: Number of loop iterations.

        Returns:
            The :class:`ApplicationResult`.
        """
        return ApplicationResult(
            status=status,
            context=self.context,
            timeline=tuple(self.timeline.events),
            iterations=iterations,
            last_event=snapshot.page_type,
        )

    # ── Default seams (no-op, overridable) ─────────────────────

    @staticmethod
    def _default_scroll(snapshot: PageSnapshot, task: Task) -> bool:
        """No-op scroll seam (real scrolling plugs in later)."""
        return False

    @staticmethod
    def _default_screenshot(detail: str) -> str:
        """No-op screenshot seam (real capture plugs in later)."""
        return ""


def make_advance(
    agent_executor: AgentExecutor,
    observer: Observer,
) -> Advance:
    """Build an ``advance`` callable from agent primitives.

    Finds the first interactable continue/submit button in the current
    snapshot and clicks it via the agent Executor, then re-observes.

    Args:
        agent_executor: The injected agent Executor (wraps Playwright).
        observer: Callable returning the current snapshot.

    Returns:
        An ``advance`` callable for the engine.
    """
    def advance(snapshot: PageSnapshot) -> PageSnapshot:
        button = next(
            (
                b
                for b in snapshot.buttons
                if b.interactable
                and any(kw in b.text.lower() for kw in _ADVANCE_KEYWORDS)
            ),
            None,
        )
        if button is not None:
            agent_executor.execute(
                BrowserCommand(
                    action=BrowserAction.CLICK_BUTTON,
                    target=button.id,
                )
            )
        return observer()

    return advance


__all__ = ["ApplicationEngine", "make_advance", "Observer", "Advance"]
