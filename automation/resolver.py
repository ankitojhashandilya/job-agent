"""Semantic field resolver — maps a question to its actual candidate value.

Every value the agent writes comes from ``application_profile.json``
(``profile["candidate"]``), which is the single source of truth. No value
is duplicated anywhere in the project.

The resolver is pure and injected: it holds a profile dict (loaded once)
and exposes ``resolve(question_id) -> str``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import APPLICATION_PROFILE_PATH

# Canonical question id -> candidate profile key. When a question maps to
# a key present in the profile, that value is used. Everything else
# returns "" (unknown → the agent may ask or skip).
_QUESTION_TO_KEY: dict[str, str] = {
    "first_name": "first_name",
    "last_name": "last_name",
    "full_name": "full_name",
    "email": "email",
    "phone": "phone",
    "city": "city",
    "country": "country",
    "current_company": "current_company",
    "current_title": "current_title",
    "years_of_experience": "years_of_experience",
    "years_python": "years_of_experience",
    "notice_period": "notice_period",
    "current_ctc": "current_ctc",
    "expected_ctc": "expected_ctc",
    "linkedin_url": "linkedin_url",
    "github_url": "github_url",
    "portfolio_url": "portfolio_url",
}


class SemanticFieldResolver:
    """Resolves a semantic question id to a concrete candidate value.

    Attributes:
        profile: The candidate dict (flat key -> value).
        resume_path: Absolute path to the resume (for upload tasks).
    """

    def __init__(
        self,
        profile: dict[str, Any] | None = None,
        resume_path: str | None = None,
    ) -> None:
        """Initialize with injected profile data.

        Args:
            profile: The flat candidate dict from ``application_profile``.
            resume_path: Absolute path to the resume file, if available.
        """
        self.profile = dict(profile or {})
        self.resume_path = resume_path or ""

    @classmethod
    def from_application_profile(
        cls,
        path: Path = APPLICATION_PROFILE_PATH,
    ) -> SemanticFieldResolver:
        """Build a resolver from the application profile JSON file.

        Args:
            path: Path to ``application_profile.json``.

        Returns:
            A resolver seeded with the profile's candidate data.
        """
        if not path.exists():
            return cls()

        data = json.loads(path.read_text(encoding="utf-8"))
        candidate = data.get("candidate", {})
        if not isinstance(candidate, dict):
            candidate = {}

        # The candidate dict may be flat (application_profile.json) or
        # nested; normalise to a flat mapping for consistent lookup.
        flat: dict[str, Any] = {}
        for key, value in candidate.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    flat[f"{key}_{sub_key}"] = sub_value
            else:
                flat[key] = value

        resume_path = data.get("resume_path") if isinstance(data, dict) else None
        return cls(profile=flat, resume_path=str(resume_path or ""))

    def resolve(self, question_id: str) -> str:
        """Return the candidate value for a semantic question.

        Args:
            question_id: The canonical question id.

        Returns:
            The value string, or ``""`` when unknown or not in profile.
        """
        key = _QUESTION_TO_KEY.get(question_id)
        if not key:
            return ""
        value = self.profile.get(key, "")
        if value is None:
            return ""
        return str(value).strip()

    def has_value(self, question_id: str) -> bool:
        """Return whether a question has a non-empty candidate value.

        Args:
            question_id: The canonical question id.

        Returns:
            ``True`` when a value is available.
        """
        return bool(self.resolve(question_id))

    def resume_available(self) -> bool:
        """Return whether a resume path is configured."""
        return bool(self.resume_path)


__all__ = ["SemanticFieldResolver"]
