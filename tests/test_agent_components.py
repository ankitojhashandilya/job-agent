"""Unit tests for agent components: scoring, planner, safety, verifier.

Run:
    python -m pytest tests/test_agent_components.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.execute import BrowserAction, BrowserCommand
from agent.planner import RuleBasedPlanner
from agent.safety import Safety, SafetyDecision
from agent.scoring import ScoreCalculator
from agent.types import (
    Button,
    FileInput,
    FormField,
    PageSnapshot,
    TaskInfo,
)
from agent.verifier import VerificationStatus, Verifier


# ═══════════════════════════════════════════════════════════════════
# ScoreCalculator
# ═══════════════════════════════════════════════════════════════════

class TestScoreCalculator:
    def test_technical_fit_full(self):
        calc = ScoreCalculator()
        result = calc.calculate(
            llm_output={
                "matched_skills": ["Python", "SQL", "Spark"],
                "missing_skills": [],
                "reason": "Good match",
            },
            job={"title": "Senior Data Engineer", "description": "", "location": ""},
        )
        assert result["score"] > 0
        assert result["status"] in ("Apply", "Review", "Maybe", "Reject")
        assert "technical_fit" in result["subscores"]
        assert result["matched_skills"] == ["Python", "SQL", "Spark"]

    def test_technical_fit_zero(self):
        calc = ScoreCalculator()
        result = calc.calculate(
            llm_output={
                "matched_skills": [],
                "missing_skills": ["Python", "SQL"],
                "reason": "Poor match",
            },
            job={"title": "", "description": "", "location": ""},
        )
        assert result["score"] >= 0
        assert result["matched_skills"] == []

    def test_determine_status_thresholds(self):
        calc = ScoreCalculator()
        assert calc._determine_status(95) == "Apply"
        assert calc._determine_status(70) == "Review"
        assert calc._determine_status(50) == "Maybe"
        assert calc._determine_status(30) == "Reject"

    def test_uses_plural_profile_fields_and_job_context(self):
        calc = ScoreCalculator()
        calc._candidate = {
            "target_roles": ["Principal Data Engineer"],
            "preferred_locations": ["Bengaluru", "Remote"],
        }
        calc._resume = {"domains": ["Banking"]}

        result = calc.calculate(
            llm_output={
                "matched_skills": ["Python", "SQL", "Spark"],
                "missing_skills": [],
                "reason": "Strong match",
            },
            job={
                "title": "Principal Data Engineer",
                "description": "Own the banking data architecture on cloud platforms and mentor engineers.",
                "location": "Bengaluru, India (Remote)",
            },
        )

        assert result["subscores"]["seniority"] == 25
        assert result["subscores"]["location"] == 10
        assert result["subscores"]["domain"] == 10
        assert result["score"] >= 75
        assert result["status"] == "Apply"

    def test_normalize_subscore(self):
        calc = ScoreCalculator()
        assert calc._normalize_subscore(50, 35) == 35
        assert calc._normalize_subscore(10, 35) == 10
        assert calc._normalize_subscore(-5, 35) == 0
        assert calc._normalize_subscore("abc", 35) == 0

    def test_subscores_sum_to_score(self):
        calc = ScoreCalculator()
        result = calc.calculate(
            llm_output={
                "matched_skills": ["Python", "Spark", "SQL", "Airflow"],
                "missing_skills": ["Kafka"],
                "reason": "Strong technical match",
            },
            job={
                "title": "Senior Data Engineer",
                "description": "Lead the data platform architecture using Spark and Kafka",
                "location": "Bengaluru",
            },
        )
        total = sum(result["subscores"].values())
        assert abs(result["score"] - total) <= 1


# ═══════════════════════════════════════════════════════════════════
# RuleBasedPlanner
# ═══════════════════════════════════════════════════════════════════

class TestRuleBasedPlanner:
    def test_waits_on_confirmation(self):
        planner = RuleBasedPlanner()
        snap = PageSnapshot(
            url="https://example.com/confirm",
            page_title="Confirmed",
            domain="example.com",
            page_type="confirmation",
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.WAIT

    def test_waits_on_login_required(self):
        planner = RuleBasedPlanner()
        snap = PageSnapshot(
            url="https://example.com/login",
            page_title="Sign In",
            domain="example.com",
            page_type="login_required",
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.WAIT

    def test_fills_empty_field(self):
        task = TaskInfo(
            resume_path="/dev/null",
            candidate={"first_name": "John"},
        )
        planner = RuleBasedPlanner(task=task)
        snap = PageSnapshot(
            url="https://example.com/form",
            page_title="Form",
            domain="example.com",
            page_type="application_form",
            fields=[
                FormField(id="field:first_name", field_type="text", label="First Name", value="",
                          required=True, visible=True, enabled=True, readonly=False, interactable=True),
            ],
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.FILL_FIELD
        assert cmd.target == "field:first_name"

    def test_skips_filled_field(self):
        task = TaskInfo(
            resume_path="/dev/null",
            candidate={"first_name": "John"},
        )
        planner = RuleBasedPlanner(task=task)
        snap = PageSnapshot(
            url="https://example.com/form",
            page_title="Form",
            domain="example.com",
            page_type="application_form",
            fields=[
                FormField(id="field:first_name", field_type="text", label="First Name", value="John"),
            ],
        )
        cmd = planner.plan(snap)
        # Should not fill an already-filled field
        assert not (cmd.action == BrowserAction.FILL_FIELD and cmd.target == "field:first_name")

    def test_uploads_file_when_missing(self):
        task = TaskInfo(
            resume_path="/path/to/resume.pdf",
            candidate={},
        )
        planner = RuleBasedPlanner(task=task)
        snap = PageSnapshot(
            url="https://example.com/form",
            page_title="Form",
            domain="example.com",
            page_type="application_form",
            file_inputs=[
                FileInput(id="upload:resume", label="Resume", has_file=False, visible=True, enabled=True, interactable=True),
            ],
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.UPLOAD_FILE
        assert cmd.target == "upload:resume"

    def test_clicks_continue_button(self):
        planner = RuleBasedPlanner()
        snap = PageSnapshot(
            url="https://example.com/form",
            page_title="Form",
            domain="example.com",
            page_type="application_form",
            buttons=[
                Button(id="button:continue", text="Continue", visible=True, enabled=True, interactable=True),
            ],
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.CLICK_BUTTON
        assert cmd.target == "button:continue"

    def test_clicks_linkedin_easy_apply_from_a_job_detail_page(self):
        planner = RuleBasedPlanner()
        snap = PageSnapshot(
            url="https://www.linkedin.com/jobs/view/123",
            page_title="Data Engineer | LinkedIn",
            domain="www.linkedin.com",
            page_type="job_details",
            buttons=[Button(id="button:easy_apply", text="Easy Apply", interactable=True)],
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.CLICK_BUTTON
        assert cmd.target == "button:easy_apply"

    def test_opens_generic_linkedin_apply_from_a_job_detail_page(self):
        planner = RuleBasedPlanner()
        snap = PageSnapshot(
            url="https://www.linkedin.com/jobs/view/123",
            page_title="Data Engineer | LinkedIn",
            domain="www.linkedin.com",
            page_type="job_details",
            buttons=[Button(id="button:apply", text="Apply", interactable=True)],
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.CLICK_BUTTON
        assert cmd.target == "button:apply"

    def test_entry_case_does_not_call_layout_fallback_for_header_fields(self):
        class Fallback:
            def resolve_candidate_key(self, label, candidate):
                raise AssertionError("The layout fallback must not run before entry routing")

        planner = RuleBasedPlanner(
            task=TaskInfo(resume_path="", candidate={"email": "person@example.com"}),
            layout_fallback=Fallback(),
        )
        snap = PageSnapshot(
            url="https://www.linkedin.com/jobs/view/123",
            page_title="Data Engineer | LinkedIn",
            domain="www.linkedin.com",
            page_type="job_details",
            fields=[FormField(id="field:search", field_type="text", label="Search", value="")],
            buttons=[Button(id="button:apply", text="Apply", interactable=True)],
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.CLICK_BUTTON
        assert cmd.target == "button:apply"

    def test_profile_share_handoff_opens_only_supported_ats_destination(self):
        planner = RuleBasedPlanner()
        snap = PageSnapshot(
            url="https://www.linkedin.com/jobs/view/123",
            page_title="Data Engineer | LinkedIn",
            domain="www.linkedin.com",
            page_type="external_apply_started",
            buttons=[
                Button(
                    id="button:continue_application",
                    text="Continue to application",
                    href="https://company.wd1.myworkdayjobs.com/en-US/job/123",
                )
            ],
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.CLICK_BUTTON
        assert cmd.target == "button:continue_application"

    def test_profile_share_handoff_rejects_unknown_destination(self):
        planner = RuleBasedPlanner()
        snap = PageSnapshot(
            url="https://www.linkedin.com/jobs/view/123",
            page_title="Data Engineer | LinkedIn",
            domain="www.linkedin.com",
            page_type="external_apply_started",
            buttons=[
                Button(
                    id="button:continue_application",
                    text="Continue to application",
                    href="https://careers.example.org/job/123",
                )
            ],
        )
        assert planner.plan(snap).action == BrowserAction.STOP_FOR_REVIEW

    def test_requires_review_when_nothing_safe_can_be_done(self):
        planner = RuleBasedPlanner()
        snap = PageSnapshot(
            url="https://example.com/done",
            page_title="Done",
            domain="example.com",
            page_type="unknown",
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.STOP_FOR_REVIEW

    def test_requires_review_for_unknown_required_question(self):
        planner = RuleBasedPlanner(task=TaskInfo(resume_path="", candidate={}))
        snap = PageSnapshot(
            url="https://example.com/form",
            page_title="Form",
            domain="example.com",
            page_type="application_form",
            fields=[
                FormField(
                    id="field:work_authorization",
                    field_type="text",
                    label="Are you authorized to work here?",
                    value="",
                    required=True,
                ),
            ],
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.STOP_FOR_REVIEW
        assert cmd.target == "field:work_authorization"

    def test_routes_final_submit_to_safety_guard(self):
        planner = RuleBasedPlanner()
        snap = PageSnapshot(
            url="https://example.com/review",
            page_title="Review",
            domain="example.com",
            page_type="application_form",
            buttons=[Button(id="button:submit_application", text="Submit application")],
        )
        cmd = planner.plan(snap)
        assert cmd.action == BrowserAction.CLICK_BUTTON
        assert Safety.check(cmd).allowed is False

    def test_detects_final_keywords(self):
        assert RuleBasedPlanner._is_final("submit application")
        assert RuleBasedPlanner._is_final("Finish")
        assert RuleBasedPlanner._is_final("Complete")
        assert not RuleBasedPlanner._is_final("Continue")
        assert not RuleBasedPlanner._is_final("Next")


# ═══════════════════════════════════════════════════════════════════
# Safety
# ═══════════════════════════════════════════════════════════════════

class TestSafety:
    def test_allows_fill_field(self):
        cmd = BrowserCommand(action=BrowserAction.FILL_FIELD, target="field:name", value="John")
        decision = Safety.check(cmd)
        assert decision.allowed is True

    def test_allows_safe_button(self):
        cmd = BrowserCommand(action=BrowserAction.CLICK_BUTTON, target="button:continue")
        decision = Safety.check(cmd)
        assert decision.allowed is True

    def test_blocks_submit(self):
        cmd = BrowserCommand(action=BrowserAction.CLICK_BUTTON, target="button:submit")
        decision = Safety.check(cmd)
        assert decision.allowed is False
        assert "blocked" in decision.reason.lower()

    def test_blocks_submit_application(self):
        cmd = BrowserCommand(action=BrowserAction.CLICK_BUTTON, target="button:submit_application")
        decision = Safety.check(cmd)
        assert decision.allowed is False

    def test_allows_final_submit_only_with_explicit_confirmation(self):
        command = BrowserCommand(action=BrowserAction.CLICK_BUTTON, target="button:submit_application")
        assert Safety.allow_user_confirmed_submit(command, user_confirmed=False).allowed is False
        assert Safety.allow_user_confirmed_submit(command, user_confirmed=True).allowed is True

    def test_blocks_finish(self):
        cmd = BrowserCommand(action=BrowserAction.CLICK_BUTTON, target="button:finish")
        decision = Safety.check(cmd)
        assert decision.allowed is False

    def test_blocks_complete(self):
        cmd = BrowserCommand(action=BrowserAction.CLICK_BUTTON, target="button:complete")
        decision = Safety.check(cmd)
        assert decision.allowed is False

    def test_blocks_withdraw(self):
        cmd = BrowserCommand(action=BrowserAction.CLICK_BUTTON, target="button:withdraw")
        decision = Safety.check(cmd)
        assert decision.allowed is False

    def test_blocks_explicit_review_handoff(self):
        decision = Safety.check(
            BrowserCommand(
                action=BrowserAction.STOP_FOR_REVIEW,
                value="Required answer missing",
            )
        )
        assert decision.allowed is False
        assert "Required answer missing" in decision.reason

    def test_blocks_delete(self):
        cmd = BrowserCommand(action=BrowserAction.CLICK_BUTTON, target="button:delete")
        decision = Safety.check(cmd)
        assert decision.allowed is False

    def test_allows_next_button(self):
        cmd = BrowserCommand(action=BrowserAction.CLICK_BUTTON, target="button:next")
        decision = Safety.check(cmd)
        assert decision.allowed is True

    def test_allows_upload(self):
        cmd = BrowserCommand(action=BrowserAction.UPLOAD_FILE, target="upload:resume", value="/path/file.pdf")
        decision = Safety.check(cmd)
        assert decision.allowed is True

    def test_allows_scroll(self):
        cmd = BrowserCommand(action=BrowserAction.SCROLL_TO, target="field:name")
        decision = Safety.check(cmd)
        assert decision.allowed is True

    def test_allows_wait(self):
        cmd = BrowserCommand(action=BrowserAction.WAIT)
        decision = Safety.check(cmd)
        assert decision.allowed is True

    def test_decision_return_type(self):
        cmd = BrowserCommand(action=BrowserAction.CLICK_BUTTON, target="button:submit")
        decision = Safety.check(cmd)
        assert isinstance(decision, SafetyDecision)
        assert decision.command is cmd
        assert isinstance(decision.reason, str)


# ═══════════════════════════════════════════════════════════════════
# Verifier
# ═══════════════════════════════════════════════════════════════════

class TestVerifier:
    def test_success_on_confirmation(self):
        snap = PageSnapshot(
            url="https://example.com/confirm",
            page_title="Confirmed",
            domain="example.com",
            page_type="confirmation",
            status_message="Your application has been submitted",
        )
        assert Verifier.verify(snap) == VerificationStatus.SUCCESS

    def test_success_on_status_message(self):
        snap = PageSnapshot(
            url="https://example.com/confirm",
            page_title="Thanks",
            domain="example.com",
            page_type="unknown",
            status_message="Application submitted successfully",
        )
        assert Verifier.verify(snap) == VerificationStatus.SUCCESS

    def test_account_required(self):
        snap = PageSnapshot(
            url="https://example.com/login",
            page_title="Sign In",
            domain="example.com",
            page_type="login_required",
        )
        assert Verifier.verify(snap) == VerificationStatus.ACCOUNT_REQUIRED

    def test_failed_on_errors(self):
        snap = PageSnapshot(
            url="https://example.com/form",
            page_title="Form",
            domain="example.com",
            page_type="application_form",
            error_messages=["This field is required"],
        )
        assert Verifier.verify(snap) == VerificationStatus.FAILED

    def test_failed_on_unavailable(self):
        snap = PageSnapshot(
            url="https://example.com/expired",
            page_title="Not Found",
            domain="example.com",
            page_type="unavailable",
        )
        assert Verifier.verify(snap) == VerificationStatus.FAILED

    def test_waiting_on_unfilled_required(self):
        snap = PageSnapshot(
            url="https://example.com/form",
            page_title="Form",
            domain="example.com",
            page_type="application_form",
            fields=[
                FormField(id="field:name", field_type="text", label="Name", value="",
                          required=True),
            ],
        )
        assert Verifier.verify(snap) == VerificationStatus.WAITING

    def test_waiting_on_search(self):
        snap = PageSnapshot(
            url="https://example.com/search",
            page_title="Search",
            domain="example.com",
            page_type="search",
        )
        assert Verifier.verify(snap) == VerificationStatus.WAITING

    def test_unknown_on_no_fields(self):
        snap = PageSnapshot(
            url="https://example.com/unknown",
            page_title="Unknown",
            domain="example.com",
            page_type="unknown",
        )
        assert Verifier.verify(snap) == VerificationStatus.UNKNOWN

    def test_waiting_on_form_with_action(self):
        snap = PageSnapshot(
            url="https://example.com/form",
            page_title="Form",
            domain="example.com",
            page_type="application_form",
            fields=[
                FormField(id="field:name", field_type="text", label="Name", value="John"),
            ],
            buttons=[
                Button(id="button:continue", text="Continue", interactable=True),
            ],
        )
        assert Verifier.verify(snap) == VerificationStatus.WAITING

    def test_redirect_is_failed(self):
        snap = PageSnapshot(
            url="https://example.com/redirect",
            page_title="Redirected",
            domain="example.com",
            page_type="redirect",
        )
        assert Verifier.verify(snap) == VerificationStatus.FAILED
