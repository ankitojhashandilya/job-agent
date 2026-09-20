"""Tests for config.py (single configuration model)."""

from __future__ import annotations

import os

import pytest

import config
from config import Settings


class TestSettingsModel:
    def test_singleton_is_settings(self) -> None:
        assert isinstance(config.settings, Settings)

    def test_from_env_defaults(self) -> None:
        settings = Settings.from_env()
        assert settings.ollama_model == "qwen3:8b"
        assert settings.google_sheet_name == "Job Tracker"
        assert settings.job_limit == 25
        assert settings.search_location == "India"

    def test_from_env_overrides(self, monkeypatch) -> None:
        monkeypatch.setenv("JOB_AGENT_LINKEDIN_EMAIL", "person@example.com")
        monkeypatch.setenv("JOB_AGENT_LINKEDIN_PASSWORD", "hunter2")
        monkeypatch.setenv("JOB_AGENT_SHEET_NAME", "My Sheet")
        monkeypatch.setenv("OLLAMA_MODEL", "llama3:8b")
        monkeypatch.setenv("JOB_AGENT_JOB_LIMIT", "7")
        monkeypatch.setenv("JOB_AGENT_USE_BROWSER_AGENT", "1")

        settings = Settings.from_env()
        assert settings.linkedin_email == "person@example.com"
        assert settings.linkedin_password == "hunter2"
        assert settings.google_sheet_name == "My Sheet"
        assert settings.ollama_model == "llama3:8b"
        assert settings.job_limit == 7
        assert settings.use_browser_agent is True

    def test_bool_env_parsing(self, monkeypatch) -> None:
        monkeypatch.setenv("JOB_AGENT_USE_BROWSER_AGENT", "false")
        assert Settings.from_env().use_browser_agent is False
        monkeypatch.setenv("JOB_AGENT_USE_BROWSER_AGENT", "yes")
        assert Settings.from_env().use_browser_agent is True
        monkeypatch.delenv("JOB_AGENT_USE_BROWSER_AGENT")
        assert Settings.from_env().use_browser_agent is False

    def test_int_env_parsing(self, monkeypatch) -> None:
        monkeypatch.setenv("JOB_AGENT_JOB_LIMIT", "not-a-number")
        assert Settings.from_env().job_limit == 25

    def test_google_credentials_env(self, monkeypatch) -> None:
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "C:/keys/svc.json")
        settings = Settings.from_env()
        assert str(settings.google_credentials_path).replace("\\", "/") == (
            "C:/keys/svc.json"
        )

    def test_validate_creates_directories(self, tmp_path) -> None:
        settings = Settings(
            project_dir=tmp_path,
            screenshot_dir=tmp_path / "shots",
            interview_notes_dir=tmp_path / "notes",
            log_dir=tmp_path / "logs",
        )
        warnings = settings.validate()
        assert (tmp_path / "shots").is_dir()
        assert (tmp_path / "notes").is_dir()
        assert (tmp_path / "logs").is_dir()
        assert isinstance(warnings, list)

    def test_validate_warns_on_missing_inputs(self, tmp_path) -> None:
        settings = Settings(
            project_dir=tmp_path,
            screenshot_dir=tmp_path / "shots",
            interview_notes_dir=tmp_path / "notes",
            log_dir=tmp_path / "logs",
            resume_path=tmp_path / "nope.pdf",
        )
        warnings = settings.validate()
        assert any("resume" in w for w in warnings)

    def test_validate_no_warnings_when_inputs_exist(self, tmp_path) -> None:
        resume = tmp_path / "resume.pdf"
        resume.write_text("resume", encoding="utf-8")
        settings = Settings(
            project_dir=tmp_path,
            screenshot_dir=tmp_path / "shots",
            interview_notes_dir=tmp_path / "notes",
            log_dir=tmp_path / "logs",
            resume_path=resume,
            resume_profile_path=resume,
            candidate_profile_path=resume,
            application_profile_path=resume,
        )
        warnings = settings.validate()
        assert warnings == []

    def test_missing_profile_warns(self, tmp_path) -> None:
        settings = Settings(
            project_dir=tmp_path,
            screenshot_dir=tmp_path / "shots",
            interview_notes_dir=tmp_path / "notes",
            log_dir=tmp_path / "logs",
            application_profile_path=tmp_path / "missing.json",
        )
        warnings = settings.validate()
        assert any("application profile" in w for w in warnings)


class TestModuleProjections:
    def test_all_legacy_names_present(self) -> None:
        names = [
            "PROJECT_DIR",
            "RESUME_PATH",
            "RESUME_PROFILE_PATH",
            "CANDIDATE_PROFILE_PATH",
            "APPLICATION_PROFILE_PATH",
            "JOB_RESULTS_JSON",
            "JOB_RESULTS_CSV",
            "JOB_HISTORY_JSON",
            "APPLICATIONS_JSON",
            "APPLICATIONS_CSV",
            "SCREENSHOT_DIR",
            "LOG_DIR",
            "OLLAMA_URL",
            "OLLAMA_MODEL",
            "OLLAMA_OPTIONS",
            "SEARCH_KEYWORDS",
            "SEARCH_LOCATION",
            "JOB_LIMIT",
            "APPLY_SCORE",
            "REVIEW_SCORE",
            "MAYBE_SCORE",
            "SCORING_WEIGHTS",
            "MAX_SKILLS",
            "KNOWN_SKILLS",
            "KNOWN_DOMAINS",
            "USE_BROWSER_AGENT",
            "TOP_APPLICATIONS",
            "SAFE_AUTOFILL",
            "STOP_BEFORE_SUBMIT",
            "JOB_STATUSES",
            "APPLICATION_STATUSES",
        ]
        for name in names:
            assert hasattr(config, name), name

    def test_projections_match_settings(self) -> None:
        assert config.JOB_RESULTS_JSON == config.settings.job_results_json
        assert config.APPLICATIONS_JSON == config.settings.applications_json
        assert config.USE_BROWSER_AGENT == config.settings.use_browser_agent
