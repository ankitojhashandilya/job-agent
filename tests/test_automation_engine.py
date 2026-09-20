"""Tests for automation/engine.py (the orchestrator loop)."""

from __future__ import annotations

from agent.types import Button, FormField, PageSnapshot
from automation.context import ApplicationContext
from automation.engine import ApplicationEngine, make_advance
from automation.retry import RetryEngine
from automation.rule_planner import RulePlanner
from automation.timeline import Timeline
from automation.types import ExecutionResult, TaskAction, TaskState
from automation.verification import ApplicationVerifier

from core.models import Job

from tests.test_automation_executor import FakeAgentExecutor


def make_job() -> Job:
    return Job(
        source_job_id="job_1",
        url="https://ats.example.com/jobs/1",
        company="Acme",
    )


def make_snapshot(
    page_type: str = "application_form",
    url: str = "https://ats.example.com/apply",
    fields: list[FormField] | None = None,
    buttons: list[Button] | None = None,
) -> PageSnapshot:
    return PageSnapshot(
        url=url,
        page_title="Apply",
        domain="ats.example.com",
        page_type=page_type,
        fields=fields or [],
        buttons=buttons or [],
    )


def form_field(field_id: str, label: str, value: str = "") -> FormField:
    return FormField(id=field_id, field_type="text", label=label, value=value)


class FakeObserver:
    """Simulates a multi-page application flow.

    page "form"    -> fields first_name + email
    page "review"  -> field last_name
    page "done"    -> confirmation
    """

    def __init__(self, profile: dict[str, str]) -> None:
        self.profile = profile
        self.filled: dict[str, str] = {}
        self.page = "form"
        self.call_count = 0

    def __call__(self) -> PageSnapshot:
        self.call_count += 1
        if self.page == "done":
            return make_snapshot(
                page_type="confirmation", url="https://ats.example.com/done"
            )
        if self.page == "review":
            return make_snapshot(
                page_type="application_form",
                url="https://ats.example.com/review",
                fields=[
                    form_field(
                        "field:last_name",
                        "Last name",
                        self.filled.get("last_name", ""),
                    )
                ],
                buttons=[Button(id="button:continue", text="Continue", interactable=True)],
            )
        return make_snapshot(
            page_type="application_form",
            url="https://ats.example.com/apply",
            fields=[
                form_field(
                    "field:first_name",
                    "First name",
                    self.filled.get("first_name", ""),
                ),
                form_field(
                    "field:email",
                    "Email",
                    self.filled.get("email", ""),
                ),
            ],
            buttons=[Button(id="button:continue", text="Continue", interactable=True)],
        )

    def advance(self, snapshot: PageSnapshot) -> PageSnapshot:
        """Click continue: form -> review -> done."""
        if self.page == "form":
            self.page = "review"
        elif self.page == "review":
            self.page = "done"
        return self()


class FakeFullExecutor:
    """TaskExecutor substitute that fills the fake observer's page."""

    def __init__(self, observer: FakeObserver, context: ApplicationContext) -> None:
        self.observer = observer
        self.context = context

    def execute(self, task) -> ExecutionResult:
        question = task.question
        if question in self.observer.profile:
            value = self.observer.profile[question]
            self.observer.filled[question] = value
            self.context.record_answer(question, value)
            self.context.mark_task(task.id, TaskState.DONE)
            self.context.record_execution(task.id)
            return ExecutionResult(
                task=task,
                task_state=TaskState.DONE,
                success=True,
                message=f"filled {question}",
                answered_field=question,
            )
        return ExecutionResult(
            task=task,
            task_state=TaskState.FAILED,
            success=False,
            message=f"no value for {question}",
        )


def build_engine(observer: FakeObserver, profile: dict[str, str]) -> ApplicationEngine:
    context = ApplicationContext.for_job(make_job())
    return ApplicationEngine(
        context=context,
        timeline=Timeline(),
        observer=observer,
        planner=RulePlanner(),
        executor=FakeFullExecutor(observer, context),
        verifier=ApplicationVerifier(),
        retry=RetryEngine(),
        advance=observer.advance,
        max_iterations=20,
    )


class TestEngine:
    def test_completes_application(self) -> None:
        profile = {"first_name": "Alice", "email": "alice@example.com", "last_name": "Smith"}
        observer = FakeObserver(profile)
        engine = build_engine(observer, profile)

        result = engine.run()

        assert result.status == "completed"
        event_types = [e.event_type for e in result.timeline]
        assert "Observe Page" in event_types
        assert "Extract Tasks" in event_types

    def test_records_answers_on_context(self) -> None:
        profile = {"first_name": "Alice", "email": "alice@example.com"}
        observer = FakeObserver(profile)
        engine = build_engine(observer, profile)

        engine.run()

        assert engine.context.has_answer("first_name")
        assert engine.context.has_answer("email")
        assert engine.context.reuse_answer("first_name") == "Alice"

    def test_blocks_on_login_required(self) -> None:
        class LoginObserver:
            def __call__(self) -> PageSnapshot:
                return make_snapshot(page_type="login_required")

        context = ApplicationContext.for_job(make_job())
        engine = ApplicationEngine(
            context=context,
            timeline=Timeline(),
            observer=LoginObserver(),
            planner=RulePlanner(),
            executor=FakeFullExecutor(FakeObserver({}), context),  # type: ignore[arg-type]
            verifier=ApplicationVerifier(),
            retry=RetryEngine(),
            advance=lambda snapshot: snapshot,
            max_iterations=10,
        )
        result = engine.run()
        assert result.status == "blocked"

    def test_aborts_without_continue_button(self) -> None:
        profile = {"first_name": "Alice", "email": "alice@example.com"}
        observer = FakeObserver(profile)

        class NoContinueObserver(FakeObserver):
            def advance(self, snapshot: PageSnapshot) -> PageSnapshot:
                return snapshot  # never advances

        no_continue = NoContinueObserver(profile)
        context = ApplicationContext.for_job(make_job())
        engine = ApplicationEngine(
            context=context,
            timeline=Timeline(),
            observer=no_continue,
            planner=RulePlanner(),
            executor=FakeFullExecutor(no_continue, context),  # type: ignore[arg-type]
            verifier=ApplicationVerifier(),
            retry=RetryEngine(),
            advance=no_continue.advance,
            max_iterations=5,
        )
        result = engine.run()
        assert result.status == "aborted"


class TestVerificationSnapshots:
    def test_engine_verifies_before_against_after(self) -> None:
        """Regression: the engine must diff the pre-action snapshot against
        the post-action snapshot, not compare a snapshot to itself."""
        profile = {"first_name": "Alice", "email": "alice@example.com"}
        observer = FakeObserver(profile)
        context = ApplicationContext.for_job(make_job())

        reports = []

        class RecordingVerifier(ApplicationVerifier):
            def verify(self, before, after, upload_intended=False):
                report = super().verify(before, after, upload_intended=upload_intended)
                reports.append(report)
                return report

        engine = ApplicationEngine(
            context=context,
            timeline=Timeline(),
            observer=observer,
            planner=RulePlanner(),
            executor=FakeFullExecutor(observer, context),
            verifier=RecordingVerifier(),
            retry=RetryEngine(),
            advance=observer.advance,
            max_iterations=20,
        )

        engine.run()

        assert reports, "verifier was never called"
        # Before the fix, before == after so value_persisted could never be True.
        assert any(r.value_persisted for r in reports), (
            "verification never detected a persisted value (snapshot defect)"
        )


class TestMakeAdvance:
    def test_clicks_continue_button(self) -> None:
        agent = FakeAgentExecutor()
        calls: list[PageSnapshot] = []

        def observer() -> PageSnapshot:
            snapshot = make_snapshot(
                buttons=[Button(id="button:continue", text="Continue", interactable=True)]
            )
            calls.append(snapshot)
            return snapshot

        advance = make_advance(agent, observer)  # type: ignore[arg-type]
        snapshot = make_snapshot(
            buttons=[Button(id="button:continue", text="Continue", interactable=True)]
        )
        advance(snapshot)

        assert len(agent.commands) == 1
        assert agent.commands[0].action.value == "click_button"
        assert agent.commands[0].target == "button:continue"
        assert len(calls) == 1

    def test_no_button_no_action(self) -> None:
        agent = FakeAgentExecutor()
        observer_called = [False]

        def observer() -> PageSnapshot:
            observer_called[0] = True
            return make_snapshot(buttons=[])

        advance = make_advance(agent, observer)  # type: ignore[arg-type]
        advance(make_snapshot(buttons=[]))
        assert agent.commands == []
        assert observer_called[0] is True

    def test_ignores_non_interactable_button(self) -> None:
        agent = FakeAgentExecutor()

        def observer() -> PageSnapshot:
            return make_snapshot(buttons=[])

        advance = make_advance(agent, observer)  # type: ignore[arg-type]
        advance(
            make_snapshot(
                buttons=[Button(id="button:continue", text="Continue", interactable=False)]
            )
        )
        assert agent.commands == []
