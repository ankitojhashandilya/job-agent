"""Tests for automation/tasks.py (task extraction)."""

from __future__ import annotations

from automation.tasks import add_dependencies, extract_tasks, task_from_question
from automation.types import Question, QuestionType, TaskAction


def question(
    question_id: str,
    qtype: QuestionType = QuestionType.TEXT,
    required: bool = False,
) -> Question:
    return Question(
        id=question_id,
        question_type=qtype,
        raw_label=question_id,
        required=required,
    )


class TestTaskFromQuestion:
    def test_fill_action(self) -> None:
        task = task_from_question(question("first_name"), 0)
        assert task.action == TaskAction.FILL
        assert task.id == "task_0"
        assert task.question == "first_name"
        assert task.candidate_key == "first_name"

    def test_upload_action(self) -> None:
        task = task_from_question(
            question("resume", QuestionType.FILE), 0
        )
        assert task.action == TaskAction.UPLOAD

    def test_check_action_for_boolean(self) -> None:
        task = task_from_question(
            question("authorization", QuestionType.BOOLEAN), 0
        )
        assert task.action == TaskAction.CHECK

    def test_checkbox_action(self) -> None:
        task = task_from_question(
            question("terms", QuestionType.CHECKBOX), 0
        )
        assert task.action == TaskAction.CHECK

    def test_select_action(self) -> None:
        task = task_from_question(
            question("country", QuestionType.SELECT), 0
        )
        assert task.action == TaskAction.SELECT

    def test_required_priority(self) -> None:
        required = task_from_question(question("email", required=True), 0)
        optional = task_from_question(question("linkedin_url"), 1)
        assert required.priority < optional.priority

    def test_unknown_candidate_key(self) -> None:
        task = task_from_question(question("some_random_field"), 0)
        assert task.candidate_key == ""


class TestExtractTasks:
    def test_sorted_by_priority(self) -> None:
        tasks = extract_tasks(
            [
                question("linkedin_url"),
                question("email", required=True),
                question("resume", QuestionType.FILE),
            ]
        )
        priorities = [task.priority for task in tasks]
        assert priorities == sorted(priorities)
        assert tasks[0].action == TaskAction.UPLOAD

    def test_uploads_first(self) -> None:
        tasks = extract_tasks(
            [
                question("first_name", required=True),
                question("resume", QuestionType.FILE),
            ]
        )
        assert tasks[0].action == TaskAction.UPLOAD


class TestAddDependencies:
    def test_parent_of(self) -> None:
        tasks = extract_tasks(
            [
                question("country", QuestionType.SELECT),
                question("city"),
            ]
        )
        tasks = add_dependencies(tasks, parent_of={"task_1": "task_0"})
        child = next(t for t in tasks if t.question == "city")
        assert child.dependencies == ("task_0",)

    def test_ignores_missing_parent(self) -> None:
        tasks = extract_tasks([question("city")])
        tasks = add_dependencies(tasks, parent_of={"task_0": "nope"})
        assert tasks[0].dependencies == ()

    def test_returns_unchanged_when_none(self) -> None:
        tasks = extract_tasks([question("city")])
        same = add_dependencies(tasks)
        assert same == tasks
