"""Single configuration model for job-agent.

All configuration — paths, search settings, scoring thresholds, and
environment-based secrets — is owned by the :class:`Settings` dataclass.
A single module-level ``settings`` instance is built once at import time
and every ``from config import X`` name below is a projection of it, so
existing import sites keep working unchanged.

Environment-based secrets:
    Secrets are read from environment variables (never hardcoded):
        JOB_AGENT_LINKEDIN_EMAIL / JOB_AGENT_LINKEDIN_PASSWORD
        GOOGLE_APPLICATION_CREDENTIALS
        JOB_AGENT_SHEET_NAME
        OLLAMA_URL / OLLAMA_MODEL
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent


def _env_str(name: str, default: str) -> str:
    """Return the env var value or a default."""
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Parse an integer environment variable."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


@dataclass
class Settings:
    """Immutable-in-use configuration bundle.

    Attributes:
        project_dir: Repository root.
        resume_path: Path to the candidate resume PDF.
        resume_profile_path: Parsed resume profile JSON.
        candidate_profile_path: Candidate preferences JSON.
        application_profile_path: Application/autofill profile JSON.
        job_results_json: Discovered+scored jobs export (JSON).
        job_results_csv: Discovered+scored jobs export (CSV).
        job_history_json: Incremental job history (system of record).
        applications_json: Application-run records export (JSON).
        applications_csv: Application-run records export (CSV).
        screenshot_dir: Screenshots written by the apply agent.
        interview_notes_dir: Reserved for interview prep.
        log_dir: Log output directory.
        scoring_log / apply_log / error_log: Log file paths.
        ollama_url / ollama_model: Ollama inference endpoint + model.
        ollama_options: Fixed sampling options for Ollama.
        ollama_timeout / ollama_retries: HTTP robustness settings.
        search_keywords / search_location / job_limit: Discovery defaults.
        apply_score / review_score / maybe_score: Scoring buckets.
        scoring_weights: Subscore weights for match scoring.
        max_skills / known_skills / known_domains: Resume parsing tables.
        use_browser_agent: Master switch for the browser agent pipeline.
        enable_ollama_layout_fallback: Allow a constrained label-to-profile-key
            fallback only after deterministic form rules do not match.
        top_applications: Cap for the apply stage.
        safe_autofill / stop_before_submit: Autofill safety switches.
        job_statuses / application_statuses: Status vocabularies.
        linkedin_email / linkedin_password: LinkedIn login secrets (env).
        google_credentials_path: Service-account JSON (env or default).
        google_sheet_name: Google Sheets workbook name (env).
    """

    project_dir: Path = PROJECT_DIR

    # Resume / profiles
    resume_path: Path = PROJECT_DIR / "resume.pdf"
    resume_profile_path: Path = PROJECT_DIR / "resume_profile.json"
    candidate_profile_path: Path = PROJECT_DIR / "candidate_profile.json"
    application_profile_path: Path = PROJECT_DIR / "application_profile.json"

    # Job results (exports)
    job_results_json: Path = PROJECT_DIR / "job_results.json"
    job_results_csv: Path = PROJECT_DIR / "job_results.csv"
    job_history_json: Path = PROJECT_DIR / "job_history.json"

    # Applications (exports)
    applications_json: Path = PROJECT_DIR / "applications.json"
    applications_csv: Path = PROJECT_DIR / "applications.csv"
    application_runs_json: Path = PROJECT_DIR / "application_runs.json"

    # Directories
    screenshot_dir: Path = PROJECT_DIR / "application_screenshots"
    interview_notes_dir: Path = PROJECT_DIR / "interview_notes"
    log_dir: Path = PROJECT_DIR / "logs"

    # Log files
    scoring_log: Path = PROJECT_DIR / "logs" / "scoring.log"
    apply_log: Path = PROJECT_DIR / "logs" / "apply.log"
    error_log: Path = PROJECT_DIR / "logs" / "errors.log"

    # Ollama
    ollama_url: str = "http://localhost:11434/api/generate"
    ollama_model: str = "qwen3:8b"
    ollama_options: dict[str, object] = field(
        default_factory=lambda: {"temperature": 0.0, "num_predict": 512}
    )
    ollama_timeout: int = 180
    ollama_retries: int = 3

    # LinkedIn search defaults
    search_keywords: list[str] = field(
        default_factory=lambda: [
            "Principal Data Engineer",
            "Lead Data Engineer",
            "Staff Data Engineer",
            "Senior Data Engineer",
        ]
    )
    search_location: str = "India"
    job_limit: int = 25

    # Scoring thresholds
    # These bands are calibrated against the deterministic 100-point
    # scorecard below.  They select roles for a human-review queue; browser
    # automation still has its own live-URL and pre-submit safety checks.
    apply_score: int = 75
    review_score: int = 60
    maybe_score: int = 45
    scoring_weights: dict[str, int] = field(
        default_factory=lambda: {
            "technical_fit": 35,
            "seniority": 25,
            "leadership": 15,
            "location": 10,
            "domain": 10,
            "growth": 5,
        }
    )

    # Resume parsing
    max_skills: int = 50
    known_skills: list[str] = field(
        default_factory=lambda: [
            "Python",
            "SQL",
            "PySpark",
            "Spark",
            "Snowflake",
            "Databricks",
            "BigQuery",
            "dbt",
            "Airflow",
            "Kafka",
            "GCP",
            "AWS",
            "Azure",
            "Oracle",
            "PL/SQL",
            "Hive",
            "HiveQL",
            "Hadoop",
            "Dataflow",
            "Cloud Storage",
            "Talend",
            "Informatica",
            "PowerCenter",
            "SAP BODS",
            "CI/CD",
            "GitHub",
            "Azure DevOps",
            "Jira",
            "Data Modeling",
            "Dimensional Modeling",
            "3NF",
            "Metadata",
            "Lineage",
            "Data Governance",
            "Data Quality",
            "Alation",
        ]
    )
    known_domains: list[str] = field(
        default_factory=lambda: [
            "Supply Chain",
            "Banking",
            "Pharma",
            "Financial Services",
            "Healthcare",
        ]
    )

    # Browser agent
    use_browser_agent: bool = False
    enable_ollama_layout_fallback: bool = False

    # Application automation
    top_applications: int = 5
    safe_autofill: bool = True
    stop_before_submit: bool = True

    # Status vocabularies
    job_statuses: list[str] = field(
        default_factory=lambda: ["Apply", "Review", "Maybe", "Reject"]
    )
    application_statuses: list[str] = field(
        default_factory=lambda: [
            "DISCOVERED",
            "SHORTLISTED",
            "READY_FOR_REVIEW",
            "SUBMITTED",
            "ASSESSMENT",
            "INTERVIEW",
            "REJECTED",
            "OFFER",
        ]
    )

    # Environment-based secrets
    linkedin_email: str = ""
    linkedin_password: str = ""
    google_credentials_path: Path = PROJECT_DIR / "google_service_account.json"
    google_sheet_name: str = "Job Tracker"

    # ── Loading ────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings, overlaying environment variables.

        Returns:
            A fully-populated :class:`Settings`.
        """
        settings = cls(
            linkedin_email=_env_str("JOB_AGENT_LINKEDIN_EMAIL", ""),
            linkedin_password=_env_str("JOB_AGENT_LINKEDIN_PASSWORD", ""),
            google_credentials_path=Path(
                _env_str(
                    "GOOGLE_APPLICATION_CREDENTIALS",
                    str(cls().google_credentials_path),
                )
            ),
            google_sheet_name=_env_str("JOB_AGENT_SHEET_NAME", "Job Tracker"),
            ollama_url=_env_str("OLLAMA_URL", "http://localhost:11434/api/generate"),
            ollama_model=_env_str("OLLAMA_MODEL", "qwen3:8b"),
            search_location=_env_str("JOB_AGENT_SEARCH_LOCATION", "India"),
            job_limit=_env_int("JOB_AGENT_JOB_LIMIT", 25),
            apply_score=_env_int("JOB_AGENT_APPLY_SCORE", 75),
            review_score=_env_int("JOB_AGENT_REVIEW_SCORE", 60),
            maybe_score=_env_int("JOB_AGENT_MAYBE_SCORE", 45),
            use_browser_agent=_env_bool("JOB_AGENT_USE_BROWSER_AGENT", False),
            enable_ollama_layout_fallback=_env_bool(
                "JOB_AGENT_ENABLE_OLLAMA_LAYOUT_FALLBACK", False
            ),
        )
        return settings

    # ── Validation ─────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Validate path configuration and create required directories.

        Ensures every output directory exists. Collects (does not raise
        on) missing optional input files so a fresh clone runs cleanly.

        Returns:
            A list of warning strings describing missing optional inputs.
        """
        for directory in [
            self.screenshot_dir,
            self.interview_notes_dir,
            self.log_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        for label, path in [
            ("resume", self.resume_path),
            ("resume profile", self.resume_profile_path),
            ("candidate profile", self.candidate_profile_path),
            ("application profile", self.application_profile_path),
        ]:
            if not path.exists():
                warnings.append(
                    f"Missing {label}: {path} (optional, pipeline still runs)"
                )
        return warnings


# ── Single instance + backward-compatible projections ─────────────
# Every legacy `from config import NAME` site keeps working because these
# module-level names are plain attributes of the shared `settings`.
settings = Settings.from_env()
settings.validate()

PROJECT_DIR = settings.project_dir

RESUME_PATH = settings.resume_path
RESUME_PROFILE_PATH = settings.resume_profile_path
CANDIDATE_PROFILE_PATH = settings.candidate_profile_path
APPLICATION_PROFILE_PATH = settings.application_profile_path

JOB_RESULTS_JSON = settings.job_results_json
JOB_RESULTS_CSV = settings.job_results_csv
JOB_HISTORY_JSON = settings.job_history_json

APPLICATIONS_JSON = settings.applications_json
APPLICATIONS_CSV = settings.applications_csv
APPLICATION_RUNS_JSON = settings.application_runs_json

SCREENSHOT_DIR = settings.screenshot_dir
INTERVIEW_NOTES_DIR = settings.interview_notes_dir
LOG_DIR = settings.log_dir

SCORING_LOG = settings.scoring_log
APPLY_LOG = settings.apply_log
ERROR_LOG = settings.error_log

OLLAMA_URL = settings.ollama_url
OLLAMA_MODEL = settings.ollama_model
OLLAMA_OPTIONS = settings.ollama_options
OLLAMA_TIMEOUT = settings.ollama_timeout
OLLAMA_RETRIES = settings.ollama_retries

SEARCH_KEYWORDS = settings.search_keywords
SEARCH_LOCATION = settings.search_location
JOB_LIMIT = settings.job_limit

APPLY_SCORE = settings.apply_score
REVIEW_SCORE = settings.review_score
MAYBE_SCORE = settings.maybe_score
SCORING_WEIGHTS = settings.scoring_weights

MAX_SKILLS = settings.max_skills
KNOWN_SKILLS = settings.known_skills
KNOWN_DOMAINS = settings.known_domains

USE_BROWSER_AGENT = settings.use_browser_agent
ENABLE_OLLAMA_LAYOUT_FALLBACK = settings.enable_ollama_layout_fallback

TOP_APPLICATIONS = settings.top_applications
SAFE_AUTOFILL = settings.safe_autofill
STOP_BEFORE_SUBMIT = settings.stop_before_submit

JOB_STATUSES = settings.job_statuses
APPLICATION_STATUSES = settings.application_statuses

LINKEDIN_EMAIL = settings.linkedin_email
LINKEDIN_PASSWORD = settings.linkedin_password
GOOGLE_CREDENTIALS_PATH = settings.google_credentials_path
GOOGLE_SHEET_NAME = settings.google_sheet_name

__all__ = [
    "Settings",
    "settings",
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
    "APPLICATION_RUNS_JSON",
    "SCREENSHOT_DIR",
    "INTERVIEW_NOTES_DIR",
    "LOG_DIR",
    "SCORING_LOG",
    "APPLY_LOG",
    "ERROR_LOG",
    "OLLAMA_URL",
    "OLLAMA_MODEL",
    "OLLAMA_OPTIONS",
    "OLLAMA_TIMEOUT",
    "OLLAMA_RETRIES",
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
    "ENABLE_OLLAMA_LAYOUT_FALLBACK",
    "TOP_APPLICATIONS",
    "SAFE_AUTOFILL",
    "STOP_BEFORE_SUBMIT",
    "JOB_STATUSES",
    "APPLICATION_STATUSES",
    "LINKEDIN_EMAIL",
    "LINKEDIN_PASSWORD",
    "GOOGLE_CREDENTIALS_PATH",
    "GOOGLE_SHEET_NAME",
]
