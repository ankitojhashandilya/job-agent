"""Verification — determines whether an action actually took effect.

Pure, deterministic, browser-free. Given the page snapshot *before* an
action and the snapshot *after*, the verifier answers the questions the
engine needs:

- did the value persist?       (value_persisted)
- did the upload succeed?      (upload_succeeded)
- did the page advance?        (page_advanced)
- did validation fail?         (validation_failed)
- was the application rejected? (ats_rejected)
- did new questions appear?    (new_questions_appeared)
- should the engine replan?    (should_replan)
"""

from __future__ import annotations

from agent.types import PageSnapshot
from agent.verifier import VerificationStatus, Verifier
from automation.types import VerificationReport


class ApplicationVerifier:
    """Answers the post-action verification questions.

    Attributes:
        verifier: The injected agent Verifier (DOM heuristic rules).
    """

    def __init__(self, verifier: Verifier | None = None) -> None:
        """Initialize with an optional injected verifier.

        Args:
            verifier: The agent Verifier (defaults to a fresh one).
        """
        self._verifier = verifier or Verifier()

    def verify(
        self,
        before: PageSnapshot,
        after: PageSnapshot,
        upload_intended: bool = False,
    ) -> VerificationReport:
        """Produce a verification report for an action.

        Args:
            before: Snapshot captured before the action.
            after: Snapshot captured after the action.
            upload_intended: Whether the action attempted an upload.

        Returns:
            A :class:`VerificationReport` summarising the outcome.
        """
        status = self._verifier.verify(after)

        value_persisted = self._value_persisted(before, after)
        upload_succeeded = self._upload_succeeded(before, after, upload_intended)
        page_advanced = self._page_advanced(before, after)
        validation_failed = bool(after.error_messages) and status is not None and status in (
            VerificationStatus.FAILED,
            VerificationStatus.UNKNOWN,
        )
        ats_rejected = status == VerificationStatus.FAILED and not validation_failed
        new_questions_appeared = self._new_questions_appeared(before, after)
        should_replan = (
            new_questions_appeared
            or (after.page_type == "application_form" and page_advanced)
            or (after.page_type == "login_required")
        )

        note = self._note(status, value_persisted, upload_succeeded, page_advanced)
        return VerificationReport(
            value_persisted=value_persisted,
            upload_succeeded=upload_succeeded,
            page_advanced=page_advanced,
            validation_failed=validation_failed,
            ats_rejected=ats_rejected,
            new_questions_appeared=new_questions_appeared,
            should_replan=should_replan,
            note=note,
        )

    # ── Sub-checks ─────────────────────────────────────────────

    @staticmethod
    def _value_persisted(before: PageSnapshot, after: PageSnapshot) -> bool:
        """Compare field values between snapshots for any new value."""
        before_values = {f.id: f.value for f in before.fields}
        for field in after.fields:
            prev = before_values.get(field.id)
            if prev is not None and prev != field.value and field.value:
                return True
        return False

    @staticmethod
    def _upload_succeeded(
        before: PageSnapshot,
        after: PageSnapshot,
        upload_intended: bool,
    ) -> bool:
        """A file upload succeeded when the file flag flipped on."""
        if not upload_intended:
            return False
        before_files = {f.id: f.has_file for f in before.file_inputs}
        for file_input in after.file_inputs:
            prev = before_files.get(file_input.id)
            if prev is False and file_input.has_file:
                return True
        return False

    @staticmethod
    def _page_advanced(before: PageSnapshot, after: PageSnapshot) -> bool:
        """The page advanced when URL or page type changed."""
        if before.url != after.url and after.url:
            return True
        if before.page_type != after.page_type:
            return True
        return False

    @staticmethod
    def _new_questions_appeared(
        before: PageSnapshot,
        after: PageSnapshot,
    ) -> bool:
        """New questions appeared when field count grew."""
        before_ids = {f.id for f in before.fields}
        before_files = {f.id for f in before.file_inputs}
        new_fields = {f.id for f in after.fields} - before_ids
        new_files = {f.id for f in after.file_inputs} - before_files
        return bool(new_fields or new_files)

    @staticmethod
    def _note(
        status: VerificationStatus,
        value_persisted: bool,
        upload_succeeded: bool,
        page_advanced: bool,
    ) -> str:
        """Build a short human-readable note for the report."""
        parts: list[str] = [f"status={status.value}"]
        if value_persisted:
            parts.append("value persisted")
        if upload_succeeded:
            parts.append("upload ok")
        if page_advanced:
            parts.append("page advanced")
        return "; ".join(parts)


__all__ = ["ApplicationVerifier"]
