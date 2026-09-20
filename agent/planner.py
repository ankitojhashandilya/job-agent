"""Deterministic, ATS-aware planner for the production application path."""

from __future__ import annotations

from agent.ats import assess_ats, forward_labels, is_supported_ats_url
from agent.cases import ApplicationCase, route_case
from agent.execute import BrowserAction, BrowserCommand
from agent.layout_fallback import FieldLayoutFallback
from agent.types import PageSnapshot, TaskInfo


_FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "first_name": ("first name", "given name", "forename"),
    "last_name": ("last name", "family name", "surname"),
    "full_name": ("full name", "your name"),
    "email": ("email", "e-mail"),
    "phone": ("phone", "mobile", "telephone"),
    "city": ("city", "town", "current city"),
    "country": ("country", "country of residence"),
    "current_company": ("current employer", "current company", "employer"),
    "current_title": ("current title", "current role", "current position", "job title"),
    "years_of_experience": ("years of experience", "total experience", "work experience"),
    "notice_period": ("notice period", "available from", "joining time"),
    "linkedin_url": ("linkedin", "linkedin profile"),
    "github_url": ("github", "github profile"),
    "portfolio_url": ("portfolio", "personal website", "website"),
    "authorization": ("work authorization", "authorized to work", "right to work"),
    "visa_sponsorship": ("visa sponsorship", "require sponsorship", "sponsorship"),
    "relocation": ("willing to relocate", "relocation", "relocate"),
}


class RuleBasedPlanner:
    """Select only known-safe actions and hand uncertainty to a human."""

    def __init__(
        self,
        task: TaskInfo | None = None,
        layout_fallback: FieldLayoutFallback | None = None,
    ) -> None:
        self._task = task
        self._layout_fallback = layout_fallback

    def plan(self, snapshot: PageSnapshot) -> BrowserCommand:
        if snapshot.page_type == "confirmation":
            return BrowserCommand(action=BrowserAction.WAIT, value="1", timeout_ms=1000)
        page_case = route_case(snapshot)
        if page_case in {
            ApplicationCase.LOGIN,
            ApplicationCase.CAPTCHA,
            ApplicationCase.UNAVAILABLE,
        }:
            return BrowserCommand(action=BrowserAction.WAIT, value="1", timeout_ms=1000)

        # Unsupported domains are stopped by the agent before planning. Keep
        # this planner domain-agnostic so deterministic field/form behaviour
        # can be exercised independently with fixture domains.
        if page_case is ApplicationCase.UNKNOWN_LAYOUT:
            return self._review(None, f"Unsupported or unknown application layout: {page_case.value}")

        assessment = assess_ats(snapshot)
        if page_case is ApplicationCase.LINKEDIN_ENTRY:
            # Entry routing must precede all field resolution. LinkedIn job
            # pages include global search controls, which are not application
            # fields and must never trigger the Ollama layout fallback.
            for entry_label in ("Easy Apply", "Apply"):
                for button in snapshot.buttons:
                    if button.interactable and self._is_exact_label(button.text, entry_label):
                        return BrowserCommand(BrowserAction.CLICK_BUTTON, target=button.id)
            return self._review(None, "No LinkedIn application entry control was detected.")

        if page_case is ApplicationCase.EXTERNAL_HANDOFF:
            for button in snapshot.buttons:
                if button.interactable and is_supported_ats_url(button.href):
                    return BrowserCommand(BrowserAction.CLICK_BUTTON, target=button.id)
            return self._review(
                None,
                "LinkedIn recorded the profile share, but no supported Workday or Greenhouse destination was found.",
            )

        candidate = (self._task.candidate if self._task else {}) or {}
        for field in snapshot.fields:
            if field.value or not field.interactable:
                continue
            candidate_key = self._match_label(field.label, candidate)
            if not candidate_key and self._layout_fallback:
                candidate_key = self._layout_fallback.resolve_candidate_key(field.label, candidate)
            if not candidate_key:
                continue
            value = str(candidate[candidate_key]).strip()
            if not value:
                continue
            if field.field_type in {"checkbox", "radio"}:
                if self._is_truthy(value):
                    return BrowserCommand(BrowserAction.CHECK_CHECKBOX, target=field.id, value=value)
                if field.required:
                    return self._review(field.id, f"Required boolean needs confirmation: {field.label}")
                continue
            action = BrowserAction.SELECT_OPTION if field.field_type == "select" else BrowserAction.FILL_FIELD
            return BrowserCommand(action, target=field.id, value=value)

        required_unknown = next(
            (
                field
                for field in snapshot.fields
                if field.required and not field.value and field.interactable
            ),
            None,
        )
        if required_unknown is not None:
            return self._review(
                required_unknown.id,
                f"Required question needs a human answer: {required_unknown.label or required_unknown.id}",
            )

        for upload in snapshot.file_inputs:
            if upload.has_file or not upload.interactable:
                continue
            if not self._task or not self._task.resume_path:
                return self._review(upload.id, "A required resume upload has no configured file.")
            return BrowserCommand(BrowserAction.UPLOAD_FILE, target=upload.id, value=self._task.resume_path)

        # The safety layer blocks final controls before Executor can click them.
        for button in snapshot.buttons:
            if button.interactable and self._is_final(button.text):
                return BrowserCommand(BrowserAction.CLICK_BUTTON, target=button.id)

        for preferred in forward_labels(assessment.platform):
            for button in snapshot.buttons:
                if button.interactable and self._is_safe_forward(button.text, preferred):
                    return BrowserCommand(BrowserAction.CLICK_BUTTON, target=button.id)

        return self._review(None, "No recognized safe action is available on this page.")

    @staticmethod
    def _review(target: str | None, reason: str) -> BrowserCommand:
        return BrowserCommand(BrowserAction.STOP_FOR_REVIEW, target=target, value=reason)

    @staticmethod
    def _match_label(label: str, candidate: dict) -> str | None:
        normalized = " ".join((label or "").lower().replace("_", " ").split())
        for key, aliases in _FIELD_KEYS.items():
            if any(alias in normalized for alias in aliases):
                if key in candidate:
                    return key
                for alternate in (f"work_{key}", key.replace("authorization", "work_authorization")):
                    if alternate in candidate:
                        return alternate
        for key in candidate:
            if key.replace("_", " ") in normalized:
                return key
        return None

    @staticmethod
    def _is_truthy(value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "y", "authorized", "willing"}

    @staticmethod
    def _is_final(text: str) -> bool:
        normalized = text.lower()
        return any(
            keyword in normalized
            for keyword in ("submit", "finish", "complete", "send application")
        )

    @staticmethod
    def _is_safe_forward(text: str, preferred: str) -> bool:
        normalized = " ".join(text.lower().split())
        expected = preferred.lower()
        return normalized == expected or normalized.startswith(f"{expected} ")

    @staticmethod
    def _is_exact_label(text: str, expected: str) -> bool:
        return " ".join((text or "").lower().split()) == expected.lower()
