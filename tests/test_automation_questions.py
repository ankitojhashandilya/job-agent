"""Tests for automation/questions.py (semantic understanding)."""

from __future__ import annotations

from agent.types import FileInput, FormField, PageSnapshot
from automation.questions import (
    match_canonical_id,
    question_from_field,
    question_from_upload,
    understand_page,
)
from automation.types import QuestionType


def field(label: str, field_type: str = "text", required: bool = False) -> FormField:
    return FormField(
        id=f"field:{label.lower().replace(' ', '_')}",
        field_type=field_type,
        label=label,
        value="",
        required=required,
    )


class TestMatchCanonicalId:
    def test_exact_alias(self) -> None:
        canonical, confidence = match_canonical_id("First name")
        assert canonical == "first_name"
        assert confidence >= 0.95

    def test_fuzzy_alias(self) -> None:
        canonical, confidence = match_canonical_id("First Name Please")
        assert canonical == "first_name"
        assert confidence >= 0.62

    def test_email(self) -> None:
        assert match_canonical_id("Email address")[0] == "email"

    def test_phone_variants(self) -> None:
        assert match_canonical_id("Mobile number")[0] == "phone"

    def test_current_company_variants(self) -> None:
        assert match_canonical_id("Current employer")[0] == "current_company"

    def test_unknown_label_returns_none(self) -> None:
        canonical, _ = match_canonical_id("Favorite pizza topping")
        assert canonical is None

    def test_empty_label(self) -> None:
        assert match_canonical_id("") == (None, 0.0)


class TestQuestionFromField:
    def test_email_type(self) -> None:
        question = question_from_field(field("Email", "email"))
        assert question is not None
        assert question.id == "email"
        assert question.question_type == QuestionType.EMAIL

    def test_phone_type(self) -> None:
        question = question_from_field(field("Phone", "tel"))
        assert question is not None
        assert question.question_type == QuestionType.PHONE

    def test_select_type(self) -> None:
        question = question_from_field(field("Country", "select"))
        assert question is not None
        assert question.question_type == QuestionType.SELECT

    def test_textarea(self) -> None:
        question = question_from_field(field("Cover letter", "textarea"))
        assert question is not None
        assert question.question_type == QuestionType.TEXTAREA

    def test_boolean_semantics(self) -> None:
        question = question_from_field(field("Visa sponsorship", "radio"))
        assert question is not None
        assert question.question_type == QuestionType.BOOLEAN

    def test_required_flag(self) -> None:
        question = question_from_field(field("First name", "text", required=True))
        assert question is not None
        assert question.required is True

    def test_field_ref_preserved(self) -> None:
        question = question_from_field(field("First name", "text"))
        assert question is not None
        assert question.field_ref == "field:first_name"

    def test_empty_label_returns_none(self) -> None:
        question = question_from_field(field("", "text"))
        assert question is None


class TestQuestionFromUpload:
    def test_resume(self) -> None:
        upload = FileInput(id="upload:resume", label="Upload resume")
        question = question_from_upload(upload)
        assert question is not None
        assert question.id == "resume"
        assert question.question_type == QuestionType.FILE

    def test_cover_letter(self) -> None:
        upload = FileInput(id="upload:cover", label="Upload cover letter")
        question = question_from_upload(upload)
        assert question is not None
        assert question.id == "cover_letter"
        assert question.question_type == QuestionType.FILE


class TestUnderstandPage:
    def _snapshot(self) -> PageSnapshot:
        return PageSnapshot(
            url="https://ats.example.com/apply",
            page_title="Apply",
            domain="ats.example.com",
            page_type="application_form",
            fields=[
                field("First name", "text", required=True),
                field("Email", "email", required=True),
                field("Phone", "tel"),
                field("Country", "select"),
            ],
            file_inputs=[
                FileInput(id="upload:resume", label="Upload resume"),
            ],
        )

    def test_extracts_all_questions(self) -> None:
        questions = understand_page(self._snapshot())
        ids = {q.id for q in questions}
        assert {"first_name", "email", "phone", "country", "resume"} <= ids

    def test_dedupes_by_id(self) -> None:
        snapshot = self._snapshot()
        snapshot.fields.append(field("First Name", "text"))
        questions = understand_page(snapshot)
        ids = [q.id for q in questions]
        assert ids.count("first_name") == 1
