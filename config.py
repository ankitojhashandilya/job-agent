
# config.py

from pathlib import Path

# ==============================================================================
# Base Directories
# ==============================================================================

PROJECT_DIR = Path(__file__).resolve().parent

# ==============================================================================
# Resume
# ==============================================================================

RESUME_PATH = PROJECT_DIR / "resume.pdf"
RESUME_PROFILE_PATH = PROJECT_DIR / "resume_profile.json"

# ==============================================================================
# Candidate Preferences
# ==============================================================================

CANDIDATE_PROFILE_PATH = PROJECT_DIR / "candidate_profile.json"
APPLICATION_PROFILE_PATH = PROJECT_DIR / "application_profile.json"

# ==============================================================================
# Job Results
# ==============================================================================

JOB_RESULTS_JSON = PROJECT_DIR / "job_results.json"
JOB_RESULTS_CSV = PROJECT_DIR / "job_results.csv"
JOB_HISTORY_JSON = PROJECT_DIR / "job_history.json"

# ==============================================================================
# Applications
# ==============================================================================

APPLICATIONS_JSON = PROJECT_DIR / "applications.json"
APPLICATIONS_CSV = PROJECT_DIR / "applications.csv"

SCREENSHOT_DIR = PROJECT_DIR / "application_screenshots"

# ==============================================================================
# Interview Preparation (Future)
# ==============================================================================

INTERVIEW_NOTES_DIR = PROJECT_DIR / "interview_notes"

# ==============================================================================
# Logging
# ==============================================================================

LOG_DIR = PROJECT_DIR / "logs"

SCORING_LOG = LOG_DIR / "scoring.log"
APPLY_LOG = LOG_DIR / "apply.log"
ERROR_LOG = LOG_DIR / "errors.log"

# ==============================================================================
# Ollama
# ==============================================================================

OLLAMA_URL = "http://localhost:11434/api/generate"

OLLAMA_MODEL = "qwen3:8b"

OLLAMA_OPTIONS = {
    "temperature": 0.0,
    "num_predict": 512,
}

OLLAMA_TIMEOUT = 180
OLLAMA_RETRIES = 3

# ==============================================================================
# LinkedIn Search
# ==============================================================================

SEARCH_KEYWORDS = [
    "Principal Data Engineer",
    "Lead Data Engineer",
    "Staff Data Engineer",
    "Senior Data Engineer",
]

SEARCH_LOCATION = "India"

JOB_LIMIT = 25

# ==============================================================================
# Scoring Thresholds
# ==============================================================================

APPLY_SCORE = 90
REVIEW_SCORE = 80
MAYBE_SCORE = 65

# ==============================================================================
# Weighted Scoring
# ==============================================================================

SCORING_WEIGHTS = {
    "technical_fit": 35,
    "seniority": 25,
    "leadership": 15,
    "location": 10,
    "domain": 10,
    "growth": 5,
}

# ==============================================================================
# Resume Parsing
# ==============================================================================

MAX_SKILLS = 50

KNOWN_SKILLS = [
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

KNOWN_DOMAINS = [
    "Supply Chain",
    "Banking",
    "Pharma",
    "Financial Services",
    "Healthcare",
]

# ==============================================================================
# Application Automation (Future ATS Plugins)
# ==============================================================================

TOP_APPLICATIONS = 5

SAFE_AUTOFILL = True

STOP_BEFORE_SUBMIT = True

# ==============================================================================
# Status Buckets
# ==============================================================================

JOB_STATUSES = [
    "Apply",
    "Review",
    "Maybe",
    "Reject",
]

APPLICATION_STATUSES = [
    "DISCOVERED",
    "SHORTLISTED",
    "READY_FOR_REVIEW",
    "SUBMITTED",
    "ASSESSMENT",
    "INTERVIEW",
    "REJECTED",
    "OFFER",
]

# ==============================================================================
# Ensure Required Directories Exist
# ==============================================================================

for directory in [
    SCREENSHOT_DIR,
    INTERVIEW_NOTES_DIR,
    LOG_DIR,
]:
    directory.mkdir(exist_ok=True)
