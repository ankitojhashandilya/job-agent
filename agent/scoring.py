"""Deterministic job scoring.

The LLM performs only semantic analysis — it returns matched/missing
skills, reasoning, and optional observations.  The ``ScoreCalculator``
takes that output plus the candidate profile and computes a numeric
score using fixed rules so that every run produces the same result
for the same inputs.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from config import (
    APPLY_SCORE,
    MAYBE_SCORE,
    REVIEW_SCORE,
    SCORING_WEIGHTS,
    CANDIDATE_PROFILE_PATH,
    RESUME_PROFILE_PATH,
)


@lru_cache(maxsize=1)
def _load_resume_profile() -> dict:
    if not RESUME_PROFILE_PATH.exists():
        return {}
    return json.loads(RESUME_PROFILE_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_candidate_profile() -> dict:
    if not CANDIDATE_PROFILE_PATH.exists():
        return {}
    return json.loads(CANDIDATE_PROFILE_PATH.read_text(encoding="utf-8"))


def _compute_technical_fit(
    matched_skills: list[str],
    missing_skills: list[str],
    max_points: int,
) -> int:
    total = len(matched_skills) + len(missing_skills)
    if total == 0:
        return 0
    ratio = len(matched_skills) / total
    return round(ratio * max_points)


def _compute_seniority(
    job_title: str,
    candidate_profile: dict,
    resume_profile: dict,
    max_points: int,
) -> int:
    target_roles = candidate_profile.get("target_roles") or []
    if isinstance(target_roles, str):
        target_roles = [target_roles]
    if not target_roles and candidate_profile.get("target_role"):
        # Backwards compatible with the original singular profile field.
        target_roles = [candidate_profile["target_role"]]
    if not target_roles:
        target_roles = resume_profile.get("target_roles") or []
    if isinstance(target_roles, str):
        target_roles = [target_roles]

    target_text = " ".join(str(role).lower() for role in target_roles)
    target_levels = ["principal", "lead", "staff", "senior"]
    job_levels = []

    for level in target_levels:
        if level in job_title.lower():
            job_levels.append(level)

    if not job_levels or not target_text:
        return round(max_points * 0.3)

    # Compare seniority level
    level_score = 0
    for level in job_levels:
        if level in target_text:
            level_score += 1

    if level_score > 0:
        return max_points
    return round(max_points * 0.5)


def _compute_leadership(
    job_title: str,
    job_description: str,
    matched_skills: list[str],
    max_points: int,
) -> int:
    leadership_keywords = [
        "lead", "principal", "staff", "architect", "manager",
        "head of", "director", "owner", "technical lead",
        "team lead", "mentor", "leadership",
    ]

    combined = f"{job_title} {job_description}".lower()
    matches = sum(1 for kw in leadership_keywords if kw in combined)

    if matches >= 3:
        return max_points
    if matches >= 2:
        return round(max_points * 0.7)
    if matches >= 1:
        return round(max_points * 0.4)
    return 0


def _compute_location(
    job_location: str,
    candidate_profile: dict,
    max_points: int,
) -> int:
    preferred_locations = candidate_profile.get("preferred_locations") or []
    if isinstance(preferred_locations, str):
        preferred_locations = [preferred_locations]
    if not preferred_locations and candidate_profile.get("preferred_location"):
        preferred_locations = [candidate_profile["preferred_location"]]
    preferred_locations = [
        str(location).strip().lower()
        for location in preferred_locations
        if str(location).strip()
    ]
    if not preferred_locations:
        return round(max_points * 0.5)
    job_loc_lower = (job_location or "").lower()
    if any(preferred in job_loc_lower for preferred in preferred_locations):
        return max_points
    return round(max_points * 0.3)


def _compute_domain(
    resume_profile: dict,
    job_title: str,
    job_description: str,
    max_points: int,
) -> int:
    known_domains = resume_profile.get("domains") or resume_profile.get("known_domains", [])
    if isinstance(known_domains, str):
        known_domains = [known_domains]
    if not known_domains:
        return 0

    job_text = f"{job_title} {job_description}".lower()

    matches = sum(1 for domain in known_domains if str(domain).lower() in job_text)
    if matches > 0:
        return max_points
    return round(max_points * 0.3)


def _compute_growth(
    job_description: str,
    max_points: int,
) -> int:
    growth_keywords = [
        "modern", "cloud", "migration", "greenfield", "innovation",
        "scalable", "roadmap", "strategy", "architecture",
        "kafka", "spark", "databricks", "snowflake",
        "kubernetes", "docker", "ml", "machine learning", "ai",
    ]

    desc_lower = (job_description or "").lower()
    matches = sum(1 for kw in growth_keywords if kw in desc_lower)

    if matches >= 4:
        return max_points
    if matches >= 2:
        return round(max_points * 0.6)
    if matches >= 1:
        return round(max_points * 0.3)
    return 0


class ScoreCalculator:
    """Deterministic score calculator.

    Takes the LLM's semantic analysis (matched/missing skills, reasoning)
    and the candidate/resume profiles, then computes each subscore using
    fixed rules.

    The result matches the schema that ``scorer.score_job()`` has always
    returned, so callers see no difference.
    """

    def __init__(self) -> None:
        self._resume = _load_resume_profile()
        self._candidate = _load_candidate_profile()

    @staticmethod
    def _normalize_subscore(value, max_points: int) -> int:
        try:
            value = int(value)
        except Exception:
            return 0
        return max(0, min(max_points, value))

    @staticmethod
    def _determine_status(score: int) -> str:
        if score >= APPLY_SCORE:
            return "Apply"
        if score >= REVIEW_SCORE:
            return "Review"
        if score >= MAYBE_SCORE:
            return "Maybe"
        return "Reject"

    def calculate(
        self,
        llm_output: dict,
        job: dict,
    ) -> dict:
        matched = llm_output.get("matched_skills", []) or []
        missing = llm_output.get("missing_skills", []) or []
        reason = (llm_output.get("reason") or llm_output.get("reasoning") or "").strip()
        optional = llm_output.get("optional_observations", "")

        if not isinstance(matched, list):
            matched = []
        if not isinstance(missing, list):
            missing = []

        matched = sorted({str(s).strip() for s in matched if str(s).strip()})
        missing = sorted({str(s).strip() for s in missing if str(s).strip()})

        job_title = (job.get("title") or job.get("job_title") or "")
        job_description = (job.get("description") or job.get("job_description") or "")
        job_location = (job.get("location") or job.get("job_location") or "")

        technical = _compute_technical_fit(
            matched, missing, SCORING_WEIGHTS["technical_fit"],
        )
        seniority = _compute_seniority(
            job_title, self._candidate, self._resume, SCORING_WEIGHTS["seniority"],
        )
        leadership = _compute_leadership(
            job_title, job_description, matched, SCORING_WEIGHTS["leadership"],
        )
        location = _compute_location(
            job_location, self._candidate, SCORING_WEIGHTS["location"],
        )
        domain = _compute_domain(
            self._resume, job_title, job_description, SCORING_WEIGHTS["domain"],
        )
        growth = _compute_growth(
            job_description, SCORING_WEIGHTS["growth"],
        )

        subscores = {
            "technical_fit": technical,
            "seniority": seniority,
            "leadership": leadership,
            "location": location,
            "domain": domain,
            "growth": growth,
        }

        score = sum(
            self._normalize_subscore(subscores.get(key, 0), max_points)
            for key, max_points in SCORING_WEIGHTS.items()
        )

        if not reason:
            reason = (
                f"Technical: {technical}/{SCORING_WEIGHTS['technical_fit']}, "
                f"Seniority: {seniority}/{SCORING_WEIGHTS['seniority']}, "
                f"Leadership: {leadership}/{SCORING_WEIGHTS['leadership']}."
            )

        return {
            "score": score,
            "status": self._determine_status(score),
            "reason": reason,
            "matched_skills": matched,
            "missing_skills": missing,
            "subscores": subscores,
            "optional_observations": optional,
        }
