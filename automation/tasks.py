"""Task extraction — turns semantic questions into executable tasks.

A task is a semantic step ("Upload Resume", "Fill Current Company",
"Answer Visa Sponsorship"). Tasks carry priority, confidence, required
flag, dependencies, a field reference, and a candidate value reference.
The planner selects among tasks; the executor resolves and runs them.
"""

from __future__ import annotations

from automation.types import Question, QuestionType, Task, TaskAction

# Candidate value keys known to exist (from application_profile.json).
# Tasks whose question maps to one of these get a candidate_key set.
_KNOWN_CANDIDATE_KEYS = {
    "first_name",
    "last_name",
    "full_name",
    "email",
    "phone",
    "city",
    "country",
    "current_company",
    "current_title",
    "years_of_experience",
    "notice_period",
    "current_ctc",
    "expected_ctc",
    "linkedin_url",
    "github_url",
    "portfolio_url",
    "years_python",
}

# Priority: uploads first, then required free-text, then optional.
_UPLOAD_PRIORITY = 10
_REQUIRED_FIELD_PRIORITY = 30
_OPTIONAL_FIELD_PRIORITY = 60
_BOOLEAN_PRIORITY = 40


def _action_for(question: Question) -> TaskAction:
    """Map a question type to the semantic action needed."""
    if question.question_type == QuestionType.FILE:
        return TaskAction.UPLOAD
    if question.question_type in (QuestionType.CHECKBOX, QuestionType.BOOLEAN):
        return TaskAction.CHECK
    if question.question_type == QuestionType.SELECT:
        return TaskAction.SELECT
    return TaskAction.FILL


def _priority_for(question: Question) -> int:
    """Return the numeric priority for a question."""
    if question.question_type == QuestionType.FILE:
        return _UPLOAD_PRIORITY
    if question.question_type in (QuestionType.BOOLEAN, QuestionType.CHECKBOX):
        return _BOOLEAN_PRIORITY
    if question.required:
        return _REQUIRED_FIELD_PRIORITY
    return _OPTIONAL_FIELD_PRIORITY


def _candidate_key(question_id: str) -> str:
    """Return the candidate value key for a question ("" if unknown)."""
    return question_id if question_id in _KNOWN_CANDIDATE_KEYS else ""


def task_from_question(question: Question, index: int) -> Task:
    """Build a single task from a question.

    Args:
        question: The semantic question to wrap.
        index: Sequence number used to derive a stable task id.

    Returns:
        A :class:`Task` for the question.
    """
    return Task(
        id=f"task_{index}",
        question=question.id,
        description=question.raw_label or question.id,
        action=_action_for(question),
        priority=_priority_for(question),
        required=question.required,
        field_ref=question.field_ref,
        candidate_key=_candidate_key(question.id),
    )


def extract_tasks(questions: list[Question]) -> list[Task]:
    """Extract an ordered task list from extracted questions.

    Tasks are sorted by priority (lowest number first), which gives a
    deterministic default execution order for the rule planner.

    Args:
        questions: The questions understood from the current page.

    Returns:
        A list of :class:`Task` objects, sorted by priority.
    """
    tasks = [task_from_question(q, index) for index, q in enumerate(questions)]
    return sorted(tasks, key=lambda task: (task.priority, task.id))


def add_dependencies(
    tasks: list[Task],
    parent_of: dict[str, str] | None = None,
) -> list[Task]:
    """Attach dependencies to tasks that must run in order.

    Args:
        tasks: The extracted task list.
        parent_of: Mapping of child task id -> parent task id. When a
            parent is present, the child depends on it.

    Returns:
        A new task list with ``dependencies`` populated.
    """
    if not parent_of:
        return tasks
    by_id = {task.id: task for task in tasks}
    for task in tasks:
        parent_id = parent_of.get(task.id)
        if parent_id and parent_id in by_id and parent_id != task.id:
            task = Task(
                id=task.id,
                question=task.question,
                description=task.description,
                action=task.action,
                priority=task.priority,
                required=task.required,
                dependencies=(parent_id,),
                field_ref=task.field_ref,
                candidate_key=task.candidate_key,
            )
            by_id[task.id] = task
    return sorted(by_id.values(), key=lambda task: (task.priority, task.id))


__all__ = ["extract_tasks", "task_from_question", "add_dependencies"]
