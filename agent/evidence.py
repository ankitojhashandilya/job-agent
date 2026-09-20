"""Evidence contract for the only successful pre-submit outcome.

``review_ready`` is intentionally strict: a run must supply proof rather
than merely stop on a page that looks application-like.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from agent.types import ActionRecord, PageSnapshot


@dataclass(frozen=True)
class ReviewEvidence:
    application_form_opened: bool
    required_fields_completed: bool
    resume_required: bool
    resume_uploaded: bool
    validation_clear: bool
    final_review_detected: bool
    screenshot_path: str
    final_url: str
    snapshot: dict[str, object]
    timeline: tuple[dict[str, object], ...]

    @property
    def verified(self) -> bool:
        return (
            self.application_form_opened
            and self.required_fields_completed
            and (not self.resume_required or self.resume_uploaded)
            and self.validation_clear
            and self.final_review_detected
            and bool(self.screenshot_path)
            and bool(self.final_url)
            and bool(self.snapshot)
            and bool(self.timeline)
        )

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["verified"] = self.verified
        return data


def redacted_snapshot(snapshot: PageSnapshot) -> dict[str, object]:
    """Serialize a page without saving applicant-entered values."""
    return {
        "url": snapshot.url,
        "page_title": snapshot.page_title,
        "domain": snapshot.domain,
        "page_type": snapshot.page_type,
        "fields": [
            {
                "id": field.id,
                "type": field.field_type,
                "label": field.label,
                "required": field.required,
                "filled": bool(field.value),
                "interactable": field.interactable,
            }
            for field in snapshot.fields
        ],
        "file_inputs": [
            {
                "id": upload.id,
                "label": upload.label,
                "required": upload.required,
                "has_file": upload.has_file,
            }
            for upload in snapshot.file_inputs
        ],
        "buttons": [
            {"id": button.id, "text": button.text, "type": button.button_type}
            for button in snapshot.buttons
        ],
        "error_messages": list(snapshot.error_messages),
        "status_message": snapshot.status_message,
        "observation_timestamp": snapshot.observation_timestamp,
    }


def make_review_evidence(
    snapshot: PageSnapshot | None,
    *,
    application_form_opened: bool,
    resume_uploaded: bool,
    final_review_detected: bool,
    screenshot_path: str,
    timeline: Iterable[ActionRecord],
) -> ReviewEvidence:
    """Build privacy-safe evidence from the final observation and actions."""
    if snapshot is None:
        return ReviewEvidence(
            False, False, False, resume_uploaded, False, final_review_detected,
            screenshot_path, "", {}, (),
        )
    resume_required = any(upload.required for upload in snapshot.file_inputs)
    required_fields_completed = all(
        field.value or not field.required for field in snapshot.fields
    )
    safe_timeline = tuple(
        {
            "action": item.action,
            "target": item.target or "",
            "result": item.result,
        }
        for item in timeline
    )
    return ReviewEvidence(
        application_form_opened=application_form_opened,
        required_fields_completed=required_fields_completed,
        resume_required=resume_required,
        resume_uploaded=resume_uploaded,
        validation_clear=not snapshot.error_messages,
        final_review_detected=final_review_detected,
        screenshot_path=screenshot_path,
        final_url=snapshot.url,
        snapshot=redacted_snapshot(snapshot),
        timeline=safe_timeline,
    )


__all__ = ["ReviewEvidence", "make_review_evidence", "redacted_snapshot"]
