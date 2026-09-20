"""Canonical, immutable data contracts for Browser Agent V2.

Every module inside ``automation`` communicates through these contracts —
never raw dictionaries and never Playwright objects. Immutable (frozen)
dataclasses make each value a stable, hashable handoff that cannot be
mutated mid-pipeline.

Dependency rule (one-way, enforced by convention):
    automation  -->  agent  -->  playwright
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from automation.context import ApplicationContext


# ── Enums (canonical vocabulary) ───────────────────────────────────

class QuestionType(str, Enum):
    """The concrete kind of a resolved semantic question."""

    TEXT = "text"
    TEXTAREA = "textarea"
    EMAIL = "email"
    PHONE = "phone"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    BOOLEAN = "boolean"
    NUMBER = "number"
    DATE = "date"
    FILE = "file"
    COUNTRY = "country"
    UNKNOWN = "unknown"


class TaskAction(str, Enum):
    """Higher-level semantic actions a task can require."""

    FILL = "fill"
    CHECK = "check"
    SELECT = "select"
    UPLOAD = "upload"
    CONTINUE = "continue"
    REQUEST = "request"  # ask human / mark unknown


class TaskState(str, Enum):
    """Lifecycle of a task inside an application."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"
    FAILED = "failed"


class VerificationOutcome(str, Enum):
    """Result of verifying a single high-level step."""

    SUCCESS = "success"
    NO_CHANGE = "no_change"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"


# ── Contracts ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Question:
    """A semantic question extracted from a form label.

    Attributes:
        id: Canonical semantic id (ex. ``"current_company"``).
            Multiple raw labels collapse into the same id.
        question_type: Concrete field kind inferred from the label/DOM.
        raw_label: The verbatim label/placeholder/aria text seen on the page.
        label_source: Where the text came from (label, placeholder,
            aria-label, nearby text, section, option, helper).
        confidence: Confidence (0.0–1.0) in the id/type mapping.
        required: Whether the question appears to be required.
        field_ref: Stable field id from the observer, if any.
    """

    id: str
    question_type: QuestionType
    raw_label: str
    label_source: str = "label"
    confidence: float = 1.0
    required: bool = False
    field_ref: str = ""


@dataclass(frozen=True)
class PlannerDecision:
    """The next high-level task the planner selects."""

    task_id: str
    action: TaskAction
    reason: str
    confidence: float = 1.0


@dataclass(frozen=True)
class Task:
    """A single semantic step within an application.

    Attributes:
        id: Unique task id within the application.
        question_id: The canonical question this task resolves ("" if none).
        description: Human/LLM readable description.
        action: The semantic action to perform.
        priority: Lower number = higher priority.
        required: Whether an unsolved task should abandon the run.
        dependencies: ids of other tasks that must complete first.
        field_ref: The observer field/button/file id this task targets.
        candidate_key: Semantic profile key whose value this task writes
            (ex. ``"current_company"``). If "", no candidate value.
    """

    id: str
    description: str
    action: TaskAction
    question: str = ""  # canonical question id, "" if none
    priority: int = 100
    required: bool = False
    dependencies: tuple[str, ...] = ()
    field_ref: str = ""
    candidate_key: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    """Result of executing a single task.

    Attributes:
        task_id: The task that was executed.
        task_state: New state of the task.
        success: Whether the action completed without error.
        message: Human-readable outcome.
        answered_field: canonical question key recorded on the context.
        duration_ms: execution time of the underlying action.
        warnings: any non-fatal warnings observed.
    """

    task: Task
    task_state: TaskState
    success: bool
    message: str
    answered_field: str = ""
    duration_ms: int = 0
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class VerificationReport:
    """Answers to the post-action verification questions."""

    value_persisted: bool = False
    upload_succeeded: bool = False
    page_advanced: bool = False
    validation_failed: bool = False
    ats_rejected: bool = False
    new_questions_appeared: bool = False
    should_replan: bool = False
    note: str = ""

    @property
    def ok(self) -> bool:
        """Return True if no failure signals are present."""
        return not (self.validation_failed or self.ats_rejected)


@dataclass(frozen=True)
class TimelineEvent:
    """A single recorded event on the application timeline."""

    sequence: int
    event_type: str
    timestamp: str
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialize to a JSON-compatible dict (for timeline.json)."""
        return {
            "sequence": self.sequence,
            "event": self.event_type,
            "timestamp": self.timestamp,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ApplicationResult:
    """Final outcome of a single job application run."""

    status: str
    context: ApplicationContext
    timeline: tuple[TimelineEvent, ...] = ()
    iterations: int = 0
    last_event: str = ""
    error: str = ""
