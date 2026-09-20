"""Agent loop — orchestrates the observe–plan–safety–execute–verify cycle.

This is the top-level coordinator for the browser agent.  It runs a
perception–action loop on a single Playwright ``Page`` until the
application is submitted, blocked, or the iteration limit is reached.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from playwright.sync_api import Page

from agent.ats import ATSCapability, ATSPlatform, assess_ats
from agent.execute import Executor, BrowserAction, BrowserCommand, ExecutionResult
from agent.layout_fallback import OllamaLayoutFallback
from agent.observe import observe_page
from agent.planner import RuleBasedPlanner
from agent.safety import Safety, SafetyDecision
from agent.types import ActionRecord, PageSnapshot, TaskInfo
from agent.verifier import Verifier, VerificationStatus
from config import ENABLE_OLLAMA_LAYOUT_FALLBACK

MAX_ITERATIONS = 15


class AgentResult:
    """Outcome of a single agent run on one job."""

    def __init__(
        self,
        status: str,
        snapshot: PageSnapshot | None = None,
        iterations: int = 0,
        last_action: str = "",
        reason: str = "",
        ats: str = "unknown",
        application_form_opened: bool = False,
        resume_uploaded: bool = False,
        final_review_detected: bool = False,
        fields_filled: list[str] | None = None,
        timeline: list[ActionRecord] | None = None,
        active_page: Page | None = None,
    ) -> None:
        self.status = status
        self.snapshot = snapshot
        self.iterations = iterations
        self.last_action = last_action
        self.reason = reason
        self.ats = ats
        self.application_form_opened = application_form_opened
        self.resume_uploaded = resume_uploaded
        self.final_review_detected = final_review_detected
        self.fields_filled = fields_filled or []
        self.timeline = timeline or []
        self.active_page = active_page


def _log_iteration(
    iteration: int,
    snapshot: PageSnapshot,
    planner_cmd: BrowserCommand,
    decision: SafetyDecision,
    exec_result: ExecutionResult,
    verify_status: VerificationStatus,
) -> None:
    print(f"  Iteration {iteration}")
    print(f"    Observed:   {snapshot.page_type} ({snapshot.url[:80]})")
    print(f"    Planner:    {planner_cmd.action.value} {planner_cmd.target or ''}")
    print(f"    Safety:     {'Allowed' if decision.allowed else 'Blocked: ' + decision.reason}")
    print(f"    Executor:   {'Success' if exec_result.success else 'Failed: ' + exec_result.message}")
    print(f"    Verifier:   {verify_status.value}")
    print()


def run_agent(
    page: Page,
    task: TaskInfo | None = None,
    submit_approval: Callable[[PageSnapshot, BrowserCommand], bool] | None = None,
    external_apply_approval: Callable[[PageSnapshot, BrowserCommand], bool] | None = None,
) -> AgentResult:
    """Run the agent loop on *page* for a single job application.

    Args:
        page: A Playwright page already navigated to the job.
        task: Optional task/candidate data for filling fields.
        submit_approval: Optional human-confirmation callback.  When omitted,
            all final controls remain blocked.  A truthy response permits one
            click of the already-detected final control only.
        external_apply_approval: Optional confirmation callback for the
            LinkedIn generic Apply entry point, which can share the candidate
            profile with a job poster before redirecting externally.

    Returns:
        An ``AgentResult`` describing the outcome.
    """
    executor = Executor(page)
    active_page = page
    layout_fallback = OllamaLayoutFallback() if ENABLE_OLLAMA_LAYOUT_FALLBACK else None
    planner = RuleBasedPlanner(task=task, layout_fallback=layout_fallback)
    safety = Safety()
    verifier = Verifier()

    last_action = ""
    ats = ATSPlatform.UNKNOWN.value
    application_form_opened = False
    resume_uploaded = False
    final_review_detected = False
    fields_filled: list[str] = []
    timeline: list[ActionRecord] = []
    submission_confirmation_used = False

    def finish(**kwargs) -> AgentResult:
        kwargs.setdefault("active_page", active_page)
        return AgentResult(**kwargs)

    for iteration in range(1, MAX_ITERATIONS + 1):
        # ── Observe ────────────────────────────────────────────
        try:
            snapshot = observe_page(active_page)
        except Exception as exc:
            print(f"  Iteration {iteration}")
            print(f"    Observe failed: {exc}")
            return finish(
                status="ERROR",
                iterations=iteration,
                last_action="observe",
            )

        assessment = assess_ats(snapshot)
        ats = assessment.platform.value
        if assessment.capability is not ATSCapability.SUPPORTED:
            return finish(
                status=assessment.capability.value.upper(),
                snapshot=snapshot,
                iterations=iteration,
                last_action=last_action,
                reason=assessment.reason,
                ats=ats,
                application_form_opened=application_form_opened,
                resume_uploaded=resume_uploaded,
                final_review_detected=final_review_detected,
                fields_filled=fields_filled,
                timeline=timeline,
            )
        application_form_opened = application_form_opened or snapshot.page_type == "application_form"

        # ── Verify early exit ──────────────────────────────────
        verify_status = verifier.verify(snapshot)
        if verify_status in (
            VerificationStatus.SUCCESS,
            VerificationStatus.ACCOUNT_REQUIRED,
        ):
            _log_iteration(
                iteration, snapshot,
                BrowserCommand(action=BrowserAction.WAIT),
                SafetyDecision(allowed=True, reason=""),
                ExecutionResult(success=True, action="verify", target=None, message="", duration_ms=0),
                verify_status,
            )
            return finish(
                status="SUBMISSION_DETECTED" if verify_status == VerificationStatus.SUCCESS else verify_status.value,
                snapshot=snapshot,
                iterations=iteration,
                last_action=last_action,
                ats=ats,
                application_form_opened=application_form_opened,
                resume_uploaded=resume_uploaded,
                final_review_detected=final_review_detected,
                fields_filled=fields_filled,
                timeline=timeline,
            )

        # ── Plan ───────────────────────────────────────────────
        try:
            cmd = planner.plan(snapshot)
        except Exception as exc:
            print(f"    Plan failed: {exc}")
            return finish(
                status="ERROR",
                snapshot=snapshot,
                iterations=iteration,
                last_action="plan",
            )

        last_action = f"{cmd.action.value} {cmd.target or ''}"

        # ── Safety ─────────────────────────────────────────────
        try:
            decision = safety.check(cmd)
        except Exception as exc:
            print(f"    Safety failed: {exc}")
            return finish(
                status="ERROR",
                snapshot=snapshot,
                iterations=iteration,
                last_action=last_action,
            )

        if not decision.allowed:
            final_review_detected = "Final submission blocked" in decision.reason
            if final_review_detected and submit_approval and not submission_confirmation_used:
                submission_confirmation_used = True
                user_confirmed = bool(submit_approval(snapshot, cmd))
                confirmed_decision = safety.allow_user_confirmed_submit(cmd, user_confirmed)
                if confirmed_decision.allowed:
                    exec_result = executor.execute(cmd)
                    active_page = getattr(executor, "page", active_page)
                    timeline.append(
                        ActionRecord(
                            action="user_confirmed_submit",
                            target=cmd.target,
                            value=None,
                            result="ok" if exec_result.success else "failed",
                            confidence=1.0,
                        )
                    )
                    _log_iteration(
                        iteration,
                        snapshot,
                        cmd,
                        confirmed_decision,
                        exec_result,
                        verify_status,
                    )
                    if not exec_result.success:
                        return finish(
                            status="FAILED",
                            snapshot=snapshot,
                            iterations=iteration,
                            last_action=last_action,
                            reason="The user-confirmed final action could not be completed.",
                            ats=ats,
                            application_form_opened=application_form_opened,
                            resume_uploaded=resume_uploaded,
                            final_review_detected=final_review_detected,
                            fields_filled=fields_filled,
                            timeline=timeline,
                        )
                    # Re-observe on the next iteration and require a real ATS
                    # confirmation before reporting a submitted application.
                    time.sleep(0.5)
                    continue
            timeline.append(
                ActionRecord(
                    action=cmd.action.value,
                    target=cmd.target,
                    value=None,
                    result="blocked",
                    confidence=1.0,
                )
            )
            _log_iteration(iteration, snapshot, cmd, decision,
                           ExecutionResult(success=False, action=cmd.action.value, target=cmd.target,
                                           message=decision.reason, duration_ms=0),
                           verify_status)
            return finish(
                status="REVIEW_READY_CANDIDATE" if final_review_detected else "MANUAL_REQUIRED",
                snapshot=snapshot,
                iterations=iteration,
                last_action=last_action,
                reason=decision.reason,
                ats=ats,
                application_form_opened=application_form_opened,
                resume_uploaded=resume_uploaded,
                final_review_detected=final_review_detected,
                fields_filled=fields_filled,
                timeline=timeline,
            )

        # ── Execute ────────────────────────────────────────────
        is_external_linkedin_apply = (
            snapshot.page_type == "job_details"
            and cmd.action is BrowserAction.CLICK_BUTTON
            and (cmd.target or "").lower() == "button:apply"
        )
        if is_external_linkedin_apply:
            approved = bool(external_apply_approval and external_apply_approval(snapshot, cmd))
            if not approved:
                return finish(
                    status="MANUAL_REQUIRED",
                    snapshot=snapshot,
                    iterations=iteration,
                    last_action=last_action,
                    reason="LinkedIn Apply can share your profile with the job poster; explicit confirmation is required.",
                    ats=ats,
                    application_form_opened=application_form_opened,
                    resume_uploaded=resume_uploaded,
                    final_review_detected=final_review_detected,
                    fields_filled=fields_filled,
                    timeline=timeline,
                )
        try:
            exec_result = executor.execute(cmd)
            active_page = getattr(executor, "page", active_page)
        except Exception as exc:
            print(f"    Execute failed: {exc}")
            return finish(
                status="ERROR",
                snapshot=snapshot,
                iterations=iteration,
                last_action=last_action,
            )

        timeline.append(
            ActionRecord(
                action=cmd.action.value,
                target=cmd.target,
                value=None,
                result="ok" if exec_result.success else "failed",
                confidence=1.0,
            )
        )
        if exec_result.success and cmd.action == BrowserAction.UPLOAD_FILE:
            resume_uploaded = True
        if exec_result.success and cmd.action in {
            BrowserAction.FILL_FIELD,
            BrowserAction.SELECT_OPTION,
            BrowserAction.CHECK_CHECKBOX,
        } and cmd.target:
            fields_filled.append(cmd.target)

        # ── Verify after execution ─────────────────────────────
        try:
            snapshot = observe_page(active_page)
            verify_status = verifier.verify(snapshot)
        except Exception:
            verify_status = VerificationStatus.UNKNOWN

        _log_iteration(iteration, snapshot, cmd, decision, exec_result, verify_status)

        if verify_status == VerificationStatus.SUCCESS:
            return finish(
                status="SUBMISSION_DETECTED",
                snapshot=snapshot,
                iterations=iteration,
                last_action=last_action,
                ats=ats,
                application_form_opened=application_form_opened,
                resume_uploaded=resume_uploaded,
                final_review_detected=final_review_detected,
                fields_filled=fields_filled,
                timeline=timeline,
            )

        if verify_status == VerificationStatus.FAILED:
            return finish(
                status="FAILED",
                snapshot=snapshot,
                iterations=iteration,
                last_action=last_action,
                reason="Validation errors or an ATS failure were detected after the action.",
                ats=ats,
                application_form_opened=application_form_opened,
                resume_uploaded=resume_uploaded,
                final_review_detected=final_review_detected,
                fields_filled=fields_filled,
                timeline=timeline,
            )

        if not exec_result.success:
            return finish(
                status="FAILED",
                snapshot=snapshot,
                iterations=iteration,
                last_action=last_action,
                ats=ats,
                application_form_opened=application_form_opened,
                resume_uploaded=resume_uploaded,
                final_review_detected=final_review_detected,
                fields_filled=fields_filled,
                timeline=timeline,
            )

        # Small pause between iterations for page to settle
        time.sleep(0.5)

    return finish(
        status="TIMEOUT",
        snapshot=snapshot if 'snapshot' in locals() else None,
        iterations=MAX_ITERATIONS,
        last_action=last_action,
        ats=ats,
        application_form_opened=application_form_opened,
        resume_uploaded=resume_uploaded,
        final_review_detected=final_review_detected,
        fields_filled=fields_filled,
        timeline=timeline,
    )
