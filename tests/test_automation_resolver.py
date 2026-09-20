"""Tests for automation/resolver.py (semantic field resolver)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation.resolver import SemanticFieldResolver


class TestSemanticFieldResolver:
    def test_resolve_known_question(self) -> None:
        resolver = SemanticFieldResolver(
            profile={"first_name": "Alice", "email": "alice@example.com"}
        )
        assert resolver.resolve("first_name") == "Alice"
        assert resolver.resolve("email") == "alice@example.com"

    def test_resolve_missing_returns_empty(self) -> None:
        resolver = SemanticFieldResolver(profile={})
        assert resolver.resolve("first_name") == ""

    def test_resolve_unknown_question_returns_empty(self) -> None:
        resolver = SemanticFieldResolver(profile={"first_name": "Alice"})
        assert resolver.resolve("totally_unknown") == ""

    def test_strips_values(self) -> None:
        resolver = SemanticFieldResolver(profile={"first_name": "  Alice  "})
        assert resolver.resolve("first_name") == "Alice"

    def test_none_value_returns_empty(self) -> None:
        resolver = SemanticFieldResolver(profile={"first_name": None})
        assert resolver.resolve("first_name") == ""

    def test_has_value(self) -> None:
        resolver = SemanticFieldResolver(
            profile={"first_name": "Alice", "last_name": ""}
        )
        assert resolver.has_value("first_name") is True
        assert resolver.has_value("last_name") is False

    def test_resume_available(self) -> None:
        resolver = SemanticFieldResolver(resume_path="resume.pdf")
        assert resolver.resume_available() is True
        assert SemanticFieldResolver().resume_available() is False

    def test_years_python_maps_to_years_of_experience(self) -> None:
        resolver = SemanticFieldResolver(profile={"years_of_experience": "11"})
        assert resolver.resolve("years_python") == "11"

    def test_from_application_profile_flat(self, tmp_path: Path) -> None:
        profile = tmp_path / "application_profile.json"
        profile.write_text(
            json.dumps(
                {
                    "resume_path": "resume.pdf",
                    "candidate": {"first_name": "Bob", "years_of_experience": "5"},
                }
            ),
            encoding="utf-8",
        )
        resolver = SemanticFieldResolver.from_application_profile(profile)
        assert resolver.resolve("first_name") == "Bob"
        assert resolver.resolve("years_of_experience") == "5"
        assert resolver.resume_path == "resume.pdf"

    def test_from_application_profile_nested(self, tmp_path: Path) -> None:
        profile = tmp_path / "application_profile.json"
        profile.write_text(
            json.dumps(
                {
                    "candidate": {
                        "first_name": "Bob",
                        "contact": {"email": "bob@example.com"},
                    }
                }
            ),
            encoding="utf-8",
        )
        resolver = SemanticFieldResolver.from_application_profile(profile)
        assert resolver.resolve("first_name") == "Bob"
        assert resolver.profile["contact_email"] == "bob@example.com"

    def test_from_application_profile_missing_file(self, tmp_path: Path) -> None:
        resolver = SemanticFieldResolver.from_application_profile(
            tmp_path / "nope.json"
        )
        assert resolver.profile == {}
        assert resolver.resume_path == ""

    def test_from_application_profile_bad_candidate(self, tmp_path: Path) -> None:
        profile = tmp_path / "application_profile.json"
        profile.write_text(json.dumps({"candidate": "not-a-dict"}), encoding="utf-8")
        resolver = SemanticFieldResolver.from_application_profile(profile)
        assert resolver.profile == {}
