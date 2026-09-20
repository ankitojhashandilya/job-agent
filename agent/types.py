from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FormField:
    """A visible form input field on the page.

    Attributes:
        id: Stable reference ID for this field.
            Used by the planner to target specific fields.
        field_type: HTML input type — "text", "email", "tel",
            "textarea", "select", "checkbox", "radio", etc.
        label: Human-readable label extracted from aria-label,
            placeholder, or associated <label> element.
        value: Current value of the field (empty string if blank).
        required: Whether the field appears to be required.
        visible: Whether the field is currently visible.
        enabled: Whether the field is enabled for input.
        readonly: Whether the field is read-only.
        interactable: Whether the field can be interacted with
            (visible AND enabled AND NOT readonly).
    """

    id: str
    field_type: str
    label: str
    value: str
    required: bool = False
    visible: bool = True
    enabled: bool = True
    readonly: bool = False
    interactable: bool = True


@dataclass
class Button:
    """A clickable button or link on the page.

    Attributes:
        id: Stable reference ID.
        text: Visible text content of the button.
        button_type: "button" for standard <button>,
            "submit" for submit-type buttons,
            "link" for <a> elements styled as buttons.
        visible: Whether the button is currently visible.
        enabled: Whether the button is enabled for interaction.
        interactable: Whether the button can be clicked
            (visible AND enabled).
        href: Destination URL for link-style buttons, if present.
    """

    id: str
    text: str
    button_type: str = "button"
    visible: bool = True
    enabled: bool = True
    interactable: bool = True
    href: str = ""


@dataclass
class FileInput:
    """A file upload field on the page.

    Attributes:
        id: Stable reference ID.
        label: Human-readable label for the upload field.
        has_file: True if a file is already selected/uploaded.
        required: Whether the form requires a document at this point.
        visible: Whether the upload field is currently visible.
        enabled: Whether the upload field is enabled.
        interactable: Whether the field can be used
            (visible AND enabled).
    """

    id: str
    label: str
    has_file: bool = False
    required: bool = False
    visible: bool = True
    enabled: bool = True
    interactable: bool = True


@dataclass
class PageSnapshot:
    """A read-only structured representation of the current browser page.

    This is the output of the observer and the primary input to the
    planner. It contains everything the LLM needs to decide the next
    action, with no raw HTML or CSS selectors.

    Attributes:
        url: Current page URL.
        page_title: Document title from the page's <title> element.
        domain: Domain extracted from the URL (e.g. "linkedin.com").
        page_type: High-level classification:
            - "application_form" — form with fillable fields (name, email, etc.)
            - "search"           — job search listings with search/filter inputs
            - "job_details"      — single job posting details (no extensive form)
            - "confirmation"     — application has been submitted
            - "login_required"   — sign-in wall preventing progress
            - "unavailable"      — job posting no longer exists
            - "redirect"         — detected redirect away from expected page
            - "unknown"          — could not classify
        fields: Visible text/input/select form fields.
        buttons: Visible clickable buttons.
        file_inputs: Visible file upload fields.
        error_messages: Validation or error text visible on the page.
        status_message: Success or informational text visible.
        observation_timestamp: ISO 8601 timestamp of when the
            observation was captured.
        observation_id: Unique identifier for this observation
            (hex string). Used for deduplication and history tracking.
    """

    url: str
    page_title: str
    domain: str
    page_type: str
    fields: list[FormField] = field(default_factory=list)
    buttons: list[Button] = field(default_factory=list)
    file_inputs: list[FileInput] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)
    status_message: str = ""
    observation_timestamp: str = ""
    observation_id: str = ""


@dataclass
class ActionRecord:
    """A recorded action from the agent's history.

    Attributes:
        action: The action type that was taken.
        target: The element ID that was targeted.
        value: The value that was provided (if applicable).
        result: "ok" if the action succeeded, "failed" otherwise.
        confidence: The planner's confidence in this action (0–1).
    """

    action: str
    target: str | None
    value: str | None
    result: str
    confidence: float


@dataclass
class TaskInfo:
    """Configuration and candidate data for a single job application.

    Attributes:
        resume_path: Absolute path to the resume PDF.
        candidate: Flat dict of candidate field key → value pairs.
        must_fill: Subset of candidate keys that should be filled
            whenever a matching field label is found.
        optional: Subset of candidate keys to fill on best-effort.
    """

    resume_path: str
    candidate: dict[str, Any]
    must_fill: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)


@dataclass
class ApplicationState:
    """Complete state passed to the planner on every iteration.

    Attributes:
        page: The current page observation.
        task: Task configuration and candidate data.
        history: Recent action history (last 5 actions).
        step_number: Current step in the agent loop (1-indexed).
        max_steps: Maximum allowed steps before abort.
    """

    page: PageSnapshot
    task: TaskInfo
    history: list[ActionRecord] = field(default_factory=list)
    step_number: int = 1
    max_steps: int = 20


@dataclass
class ToolCall:
    """A decision produced by the planner — the next action to take.

    Attributes:
        action: One of the seven supported action types.
            "fill_field"   — fill a text/input field with a value.
            "click_button" — click a button identified by its ID.
            "upload_file"  — upload a file to a file input.
            "scroll"       — scroll the page (value: "up" / "down").
            "wait"         — wait for page to settle (value: seconds).
            "done"         — goal achieved, stop the loop.
            "abort"        — cannot proceed, stop with failure.
        target: Element ID from the current PageSnapshot.
            Required for: fill_field, click_button, upload_file.
            Ignored for: scroll, wait, done, abort.
        value: Additional data depending on the action type.
            fill_field  → text to fill.
            upload_file → file path.
            scroll      → "up" or "down".
            wait        → seconds as string (e.g. "2").
            Others      → None.
        reason: One-sentence justification for this action.
        confidence: Model confidence in this decision (0.0 – 1.0).
    """

    action: str
    reason: str
    confidence: float
    target: str | None = None
    value: str | None = None
