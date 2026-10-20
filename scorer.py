# scorer.py

import hashlib
import json
import time
from functools import lru_cache

from agent.scoring import ScoreCalculator
from config import (
    APPLY_SCORE,
    CANDIDATE_PROFILE_PATH,
    MAYBE_SCORE,
    OLLAMA_MODEL,
    OLLAMA_OPTIONS,
    RESUME_PROFILE_PATH,
    REVIEW_SCORE,
    SCORING_WEIGHTS,
)
from discovery_cache import DiscoveryCache
from ollama_client import generate_json
from prompts import SCORING_PROMPT


@lru_cache(maxsize=1)
def load_resume_profile() -> dict:
    if not RESUME_PROFILE_PATH.exists():
        raise FileNotFoundError(f"Missing {RESUME_PROFILE_PATH}. Run resume_parser.py first.")

    return json.loads(RESUME_PROFILE_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_candidate_profile() -> dict:
    if not CANDIDATE_PROFILE_PATH.exists():
        return {}

    return json.loads(CANDIDATE_PROFILE_PATH.read_text(encoding="utf-8"))


def build_prompt(job: dict) -> str:
    resume_profile = load_resume_profile()
    candidate_profile = load_candidate_profile()

    # Job.to_dict() also contains raw.description. Sending the full object
    # duplicated the posting and could evict the candidate profile from context.
    semantic_job = {
        key: job.get(key, "") for key in ("title", "company", "location", "description")
    }
    compact = {"separators": (",", ":"), "ensure_ascii": False, "sort_keys": True}
    return SCORING_PROMPT.format(
        resume_profile=json.dumps(resume_profile, **compact),
        candidate_profile=json.dumps(candidate_profile, **compact),
        job=json.dumps(semantic_job, **compact),
    )


def normalize_score(value) -> int:
    try:
        value = int(value)
    except Exception:
        return 0

    if 1 <= value <= 10:
        value *= 10

    return max(0, min(100, value))


def normalize_subscore(value, max_points: int) -> int:
    try:
        value = int(value)
    except Exception:
        return 0

    return max(0, min(max_points, value))


def determine_status(score: int) -> str:
    if score >= APPLY_SCORE:
        return "Apply"

    if score >= REVIEW_SCORE:
        return "Review"

    if score >= MAYBE_SCORE:
        return "Maybe"

    return "Reject"


def default_subscores():
    return {
        "technical_fit": 0,
        "seniority": 0,
        "leadership": 0,
        "location": 0,
        "domain": 0,
        "growth": 0,
    }


def calculate_weighted_score(
    subscores: dict,
) -> int:
    return sum(
        normalize_subscore(
            subscores.get(key, 0),
            max_points,
        )
        for key, max_points in SCORING_WEIGHTS.items()
    )


def validate_response(
    response: dict,
    job: dict | None = None,
) -> dict:
    if not isinstance(response, dict):
        response = {}

    normalized = {}
    for key, value in response.items():
        if isinstance(key, str):
            cleaned_key = key.replace("\n", "").replace("\r", "").strip().strip('"').strip("'")
            normalized[cleaned_key] = value
        else:
            normalized[key] = value

    response = normalized

    reason = str(response.get("reason", "No reason provided.")).strip()

    matched_skills = response.get("matched_skills", [])
    missing_skills = response.get("missing_skills", [])

    if not isinstance(matched_skills, list):
        matched_skills = []
    if not isinstance(missing_skills, list):
        missing_skills = []

    matched_skills = sorted({str(s).strip() for s in matched_skills if str(s).strip()})
    missing_skills = sorted({str(s).strip() for s in missing_skills if str(s).strip()})

    # Compute score deterministically from the LLM's semantic analysis and
    # the original job.  The prior implementation built this data from the
    # LLM response, which intentionally does not include job metadata; that
    # made seniority, location, leadership, domain, and growth scores mostly
    # zero regardless of the actual posting.
    job = job if isinstance(job, dict) else {}
    calculator = ScoreCalculator()
    computed = calculator.calculate(
        llm_output={
            "matched_skills": matched_skills,
            "missing_skills": missing_skills,
            "reason": reason,
        },
        job=job,
    )

    return {
        "score": computed["score"],
        "status": computed["status"],
        "reason": computed["reason"],
        "matched_skills": computed["matched_skills"],
        "missing_skills": computed["missing_skills"],
        "subscores": computed["subscores"],
    }


def score_job(
    job: dict,
) -> dict:
    prompt = build_prompt(job)
    cache = DiscoveryCache()
    key = hashlib.sha256(
        json.dumps([prompt, OLLAMA_MODEL, OLLAMA_OPTIONS], sort_keys=True).encode("utf-8")
    ).hexdigest()
    response = cache.get("analysis-v1", key, 7 * 24 * 3600)
    if response is not None:
        print(f"  Reusing saved analysis: {job.get('title', '')}")
    else:
        started = time.monotonic()
        print(f"  Analyzing fit with {OLLAMA_MODEL}: {job.get('title', '')}", flush=True)
        response = generate_json(prompt)
        if (
            not isinstance(response, dict)
            or not all(key in response for key in ("matched_skills", "missing_skills", "reason"))
            or not (
                isinstance(response["matched_skills"], list)
                and isinstance(response["missing_skills"], list)
                and isinstance(response["reason"], str)
                and response["reason"].strip()
            )
        ):
            raise ValueError("Model analysis is incomplete; it has not been cached.")
        cache.put("analysis-v1", key, response)
        print(f"  Analysis completed in {time.monotonic() - started:.1f}s")
    # Recompute deterministic scoring even when semantic analysis is cached.
    result = validate_response(response, job)
    print(f"  Result: {result['status']} ({result['score']}/100)", flush=True)
    return result


def clear_profile_cache():
    load_resume_profile.cache_clear()
    load_candidate_profile.cache_clear()
