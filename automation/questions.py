"""Semantic question understanding.

Replaces the philosophy of "detect textboxes" with "understand what is
being asked". Given a structured :class:`agent.types.PageSnapshot` (the
observe contract) this module inspects labels, placeholders, aria-labels,
nearby text, options, and helper text, then collapses each raw label into
a canonical semantic question via fuzzy alias matching.

The mapper never hardcodes DOM positions — it matches on normalized text.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from agent.types import FileInput, FormField, PageSnapshot
from automation.types import Question, QuestionType

# Canonical question id -> aliases (normalized tokens).
# Alias lists use lowercase, singular, stripped phrasing. Fuzzy matching
# then tolerates minor phrasing variations.
ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "first_name": ("first name", "given name", "forename"),
    "last_name": ("last name", "family name", "surname"),
    "full_name": ("full name", "your name", "name"),
    "email": ("email", "email address", "e mail"),
    "phone": ("phone", "phone number", "mobile", "mobile number", "telephone", "contact number"),
    "city": ("city", "town", "current city"),
    "country": ("country", "country of residence", "residence country"),
    "current_company": (
        "current employer",
        "current company",
        "employer",
        "organization",
        "company name",
        "current organization",
    ),
    "current_title": ("current title", "current role", "current position", "job title", "title"),
    "years_of_experience": (
        "years of experience",
        "total experience",
        "years experience",
        "experience years",
        "work experience",
        "total years of experience",
    ),
    "years_python": ("years of python", "python experience", "python years"),
    "notice_period": (
        "notice period",
        "available from",
        "joining time",
        "days notice",
        "serving notice",
    ),
    "current_ctc": (
        "current ctc",
        "current salary",
        "current compensation",
        "current package",
    ),
    "expected_ctc": (
        "expected ctc",
        "expected salary",
        "desired salary",
        "expected compensation",
        "salary expectation",
        "compensation",
        "expected package",
    ),
    "linkedin_url": ("linkedin", "linkedin profile", "linkedin url", "linkedin link"),
    "github_url": ("github", "github profile", "github url"),
    "portfolio_url": (
        "portfolio",
        "portfolio url",
        "website",
        "personal website",
        "web url",
    ),
    "cover_letter": (
        "cover letter",
        "introduction",
        "why do you want to work here",
        "motivation letter",
    ),
    "gender": ("gender", "sex"),
    "visa_sponsorship": (
        "visa sponsorship",
        "visa required",
        "sponsorship",
        "work authorization sponsorship",
        "require visa sponsorship",
        "will you now or in the future require sponsorship",
    ),
    "relocation": (
        "relocation",
        "willing to relocate",
        "relocate",
        "ready to relocate",
        "open to relocation",
    ),
    "remote": ("remote work", "willing to work remote", "remote ready", "work from home", "hybrid"),
    "authorization": (
        "work authorization",
        "legally authorized",
        "authorized to work",
        "right to work",
        "eligible to work",
    ),
    "linkedin_profile": ("linkedin profile", "linkedin url"),
}

# Option text -> canonical boolean question (for radios/checkboxes).
_BOOLEAN_YES = re.compile(
    r"^(yes|y|true|i am willing|willing|available|authorized|sponsored)$",
    re.IGNORECASE,
)
_BOOLEAN_NO = re.compile(
    r"^(no|n|false|not authorized|not willing|no sponsorship needed)$",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, and collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[\*:?().\[\]]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _similar(a: str, b: str) -> float:
    """Return a similarity ratio between two normalized strings."""
    return SequenceMatcher(None, a, b).ratio()


def match_canonical_id(raw_label: str) -> tuple[str | None, float]:
    """Map a raw label to a canonical question id via fuzzy aliases.

    Args:
        raw_label: The raw label text seen on the page.

    Returns:
        A tuple of (canonical id, confidence). id is None when no alias
        matches above the threshold.
    """
    normalized = _normalize(raw_label)
    if not normalized:
        return None, 0.0

    best_id: str | None = None
    best_score = 0.0

    for canonical, aliases in ALIAS_GROUPS.items():
        for alias in aliases:
            alias_norm = _normalize(alias)
            # Substring match is a strong signal (ex. "Your full name").
            if alias_norm in normalized or normalized in alias_norm:
                score = 0.95
            else:
                score = _similar(alias_norm, normalized)
            if score > best_score:
                best_score = score
                best_id = canonical

    if best_score >= 0.62:
        return best_id, min(best_score, 1.0)
    return None, best_score


def _question_type(field: FormField, canonical: str | None) -> QuestionType:
    """Infer the concrete question type from the DOM field type + id."""
    ft = (field.field_type or "").lower()

    # Semantic signals take precedence over the raw DOM type: a radio or
    # checkbox whose label means "authorized to work" is a boolean
    # question, not a bare radio group.
    if canonical in (
        "authorization",
        "relocation",
        "remote",
        "visa_sponsorship",
    ):
        return QuestionType.BOOLEAN

    if ft == "textarea":
        return QuestionType.TEXTAREA
    if ft == "select":
        return QuestionType.SELECT
    if ft == "checkbox":
        return QuestionType.CHECKBOX
    if ft == "radio":
        return QuestionType.RADIO
    if ft == "email" or canonical == "email":
        return QuestionType.EMAIL
    if ft == "tel" or canonical == "phone":
        return QuestionType.PHONE
    if ft == "number" or canonical in ("years_of_experience", "years_python"):
        return QuestionType.NUMBER
    if canonical in ("country",):
        return QuestionType.COUNTRY
    if canonical == "cover_letter":
        return QuestionType.TEXTAREA
    return QuestionType.TEXT


def _is_required(field: FormField) -> bool:
    """Best-effort required detection from the observed field."""
    return bool(getattr(field, "required", False))


def question_from_field(field: FormField) -> Question | None:
    """Convert one observed form field into a semantic question.

    Args:
        field: A :class:`agent.types.FormField` from the snapshot.

    Returns:
        A :class:`Question`, or ``None`` if the field cannot be mapped.
    """
    label = (field.label or "").strip()
    if not label:
        return None

    canonical, confidence = match_canonical_id(label)
    qtype = _question_type(field, canonical)

    return Question(
        id=canonical or label,
        question_type=qtype,
        raw_label=label,
        label_source="label",
        confidence=confidence,
        required=_is_required(field),
        field_ref=field.id,
    )


def question_from_upload(upload: FileInput) -> Question | None:
    """Convert a file input into a resume/cover-letter question.

    Args:
        upload: A :class:`agent.types.FileInput` from the snapshot.

    Returns:
        A :class:`Question` for the upload, or ``None``.
    """
    label = (upload.label or "resume").strip().lower()
    if "cover" in label or "cover letter" in label:
        return Question(
            id="cover_letter",
            question_type=QuestionType.FILE,
            raw_label=upload.label or "Cover letter",
            label_source="label",
            confidence=0.9,
            field_ref=upload.id,
        )
    return Question(
        id="resume",
        question_type=QuestionType.FILE,
        raw_label=upload.label or "Resume",
        label_source="label",
        confidence=0.9,
        field_ref=upload.id,
    )


def understand_page(snapshot: PageSnapshot) -> list[Question]:
    """Extract all semantic questions from a page snapshot.

    Args:
        snapshot: The observe contract (:class:`agent.types.PageSnapshot`).

    Returns:
        An ordered list of :class:`Question` objects for the page.
    """
    questions: list[Question] = []
    seen: set[str] = set()

    for field in snapshot.fields:
        question = question_from_field(field)
        if question is None or question.id in seen:
            continue
        seen.add(question.id)
        questions.append(question)

    for upload in snapshot.file_inputs:
        question = question_from_upload(upload)
        if question.id in seen:
            continue
        seen.add(question.id)
        questions.append(question)

    return questions


__all__ = [
    "ALIAS_GROUPS",
    "match_canonical_id",
    "understand_page",
    "question_from_field",
    "question_from_upload",
]
