"""ApplicationContext — mutable, cross-page state for one application.

A single instance survives every page of one job application. Every
completed action updates the context. The context is the memory layer of
Browser Agent V2 (Phase 9): once an answer exists, the browser never asks
again — the semantic answer is reused from ``answers``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from automation.types import Task, TimelineEvent
from core.models import Job


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class ApplicationContext:
    """Mutable state of a single application run.

    Attributes:
        job_id: Source-specific job id.
        job_url: Canonical URL of the job posting.
        company: Company name.
        ats_name: Name of the ATS once detected ("" until known).
        current_page: URL/description of the current page.
        pages_completed: Number of pages completed so far.
        answers: Canonical question id -> candidate value already written.
        answered_fields: Canonical question ids answered this run.
        uploaded_files: Paths of files uploaded.
        resume_uploaded: Whether the resume was uploaded.
        cover_letter_uploaded: Whether a cover letter was uploaded.
        visited_pages: Set of page URLs already visited.
        retry_count: Number of retries consumed.
        last_error: Most recent error message ("" if none).
        warnings: Non-fatal warnings recorded.
        unknown_questions: Canonical questions the agent could not answer.
        timestamps: Named milestones (ex. started, finished).
        execution_history: Ordered log of executed task ids.
        tasks: Working set of extracted tasks (id -> Task).
        timeline: Ordered events recorded for this application.
    """

    job_id: str = ""
    job_url: str = ""
    company: str = ""
    ats_name: str = ""
    current_page: str = ""
    pages_completed: int = 0
    answers: dict[str, str] = field(default_factory=dict)
    answered_fields: list[str] = field(default_factory=list)
    uploaded_files: list[str] = field(default_factory=list)
    resume_uploaded: bool = False
    cover_letter_uploaded: bool = False
    visited_pages: set[str] = field(default_factory=set)
    retry_count: int = 0
    last_error: str = ""
    warnings: list[str] = field(default_factory=list)
    unknown_questions: list[str] = field(default_factory=list)
    timestamps: dict[str, str] = field(default_factory=dict)
    execution_history: list[str] = field(default_factory=list)
    tasks: dict[str, Task] = field(default_factory=dict)
    task_states: dict[str, object] = field(default_factory=dict)
    timeline: list[TimelineEvent] = field(default_factory=list)

    # ── Factories ──────────────────────────────────────────────

    @classmethod
    def for_job(
        cls,
        job: Job,
        ats_name: str = "",
        profile: dict[str, object] | None = None,
    ) -> ApplicationContext:
        """Build a new context seeded from a canonical Job.

        Args:
            job: The canonical job being applied to.
            ats_name: Optional known ATS slug.
            profile: Optional candidate profile used to seed answers that
                are already known (ex. first_name, email).

        Returns:
            A fresh context for a single application run.
        """
        now = _now()
        context = cls(
            job_id=job.source_job_id,
            job_url=job.url,
            company=job.company,
            ats_name=ats_name,
            current_page=job.url,
        )
        context.timestamps["started"] = now
        if profile:
            candidate = profile.get("candidate", {}) if isinstance(profile, dict) else {}
            if isinstance(candidate, dict):
                for key, value in candidate.items():
                    if value is not None and str(value).strip():
                        context.answers[key] = str(value)
        return context

    # ── Mutators (every completed action updates the context) ───

    def record_answer(self, question_id: str, value: str) -> None:
        """Persist an answer and mark the field answered (Phase 9)."""
        self.answers[question_id] = value
        if question_id not in self.answered_fields:
            self.answered_fields.append(question_id)

    def has_answer(self, question_id: str) -> bool:
        """Return whether a canonical question already has an answer."""
        return question_id in self.answers

    def reuse_answer(self, question_id: str) -> str:
        """Return the stored answer for a question ("" if absent)."""
        return self.answers.get(question_id, "")

    def record_upload(self, path: str, kind: str = "resume") -> None:
        """Record a file upload."""
        if path and path not in self.uploaded_files:
            self.uploaded_files.append(path)
        if kind == "resume":
            self.resume_uploaded = True
        if kind == "cover_letter":
            self.cover_letter_uploaded = True

    def record_visited(self, page: str) -> None:
        """Mark a page URL as visited."""
        self.visited_pages.add(page)
        self.current_page = page

    def record_error(self, message: str) -> None:
        """Record the most recent error and bump the retry counter."""
        self.last_error = message
        self.retry_count += 1

    def record_warning(self, message: str) -> None:
        """Record a non-fatal warning."""
        self.warnings.append(message)

    def record_unknown(self, question_id: str, detail: str = "") -> None:
        """Record a canonical question that could not be answered."""
        if question_id not in self.unknown_questions:
            self.unknown_questions.append(question_id)
        if detail:
            self.record_warning(f"unknown question {question_id}: {detail}")

    def record_execution(self, task_id: str) -> None:
        """Append a task id to the execution history."""
        self.execution_history.append(task_id)

    def mark_task(self, task_id: str, state: object) -> None:
        """Record the lifecycle state of a task.

        Args:
            task_id: The task id to update.
            state: New TaskState value to assign.
        """
        self.task_states[task_id] = state

    def add_timeline(self, event: TimelineEvent) -> None:
        """Append a timeline event (timestamps preserved)."""
        self.timeline.append(event)
        self.timestamps[event.event_type] = event.timestamp

    # ── Reporting ──────────────────────────────────────────────

    @property
    def completion_percentage(self) -> float:
        """Return the share of extracted tasks completed (0.0–100.0)."""
        if not self.tasks:
            return 0.0
        done = sum(
            1 for task in self.tasks.values() if task.question in self.answers
        )
        return round(done / len(self.tasks) * 100, 1)

    def snapshot(self) -> dict[str, object]:
        """Return a JSON-safe snapshot (for dashboards/debugging)."""
        return {
            "job_id": self.job_id,
            "job_url": self.job_url,
            "company": self.company,
            "ats_name": self.ats_name,
            "current_page": self.current_page,
            "pages_completed": self.pages_completed,
            "answers": dict(self.answers),
            "answered_fields": list(self.answered_fields),
            "uploaded_files": list(self.uploaded_files),
            "resume_uploaded": self.resume_uploaded,
            "cover_letter_uploaded": self.cover_letter_uploaded,
            "visited_pages": sorted(self.visited_pages),
            "retry_count": self.retry_count,
            "last_error": self.last_error,
            "warnings": list(self.warnings),
            "unknown_questions": list(self.unknown_questions),
            "timestamps": dict(self.timestamps),
                        "execution_history": list(self.execution_history),
            "completion_percentage": self.completion_percentage,
        }
