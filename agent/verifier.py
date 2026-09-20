"""Verifier — determines application state from a ``PageSnapshot`` only.

No LLM.  No browser interaction.  Pure DOM-based heuristic rules.
"""

from __future__ import annotations

from enum import Enum

from agent.types import PageSnapshot


class VerificationStatus(Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    WAITING = "WAITING"
    ACCOUNT_REQUIRED = "ACCOUNT_REQUIRED"
    UNKNOWN = "UNKNOWN"


class Verifier:
    """Determines application state by inspecting a ``PageSnapshot``.

    Rules (first match wins):

    1. **SUCCESS** — page type is ``confirmation`` OR snapshot contains
       status text matching a submission pattern.
    2. **ACCOUNT_REQUIRED** — page type is ``login_required``.
    3. **FAILED** — page has error messages visible.
    4. **WAITING** — page has empty required fields, or no visible
       action buttons, or is an ``application_form`` with unfilled fields.
    5. **UNKNOWN** — fallback.
    """

    @staticmethod
    def verify(snapshot: PageSnapshot) -> VerificationStatus:
        if snapshot.page_type == "confirmation" or snapshot.status_message:
            return VerificationStatus.SUCCESS

        if snapshot.page_type == "login_required":
            return VerificationStatus.ACCOUNT_REQUIRED

        if snapshot.error_messages:
            return VerificationStatus.FAILED

        if snapshot.page_type in ("unavailable", "redirect"):
            return VerificationStatus.FAILED

        if snapshot.page_type == "application_form":
            has_unfilled_required = any(
                f.required and not f.value for f in snapshot.fields
            )
            has_actionable_buttons = any(b.interactable for b in snapshot.buttons)

            if has_unfilled_required:
                return VerificationStatus.WAITING

            if not has_actionable_buttons and snapshot.fields:
                return VerificationStatus.WAITING

            return VerificationStatus.WAITING

        if snapshot.page_type in ("search", "job_details"):
            return VerificationStatus.WAITING

        if snapshot.page_type == "unknown" and not snapshot.fields:
            return VerificationStatus.UNKNOWN

        return VerificationStatus.UNKNOWN
