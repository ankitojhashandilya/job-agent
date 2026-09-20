"""Constrained Ollama fallback for unfamiliar form labels.

The model sees only a field label and candidate *key names*.  It never sees
candidate values, decides navigation, creates credentials, or answers unknown
questions.  The planner uses any accepted key to retrieve the existing local
candidate value itself.
"""

from __future__ import annotations

from typing import Protocol

from ollama_client import generate_json


_SAFE_CANDIDATE_KEYS = frozenset(
    {
        "first_name", "last_name", "full_name", "email", "phone", "city",
        "country", "current_company", "current_title", "years_of_experience",
        "notice_period", "linkedin_url", "github_url", "portfolio_url",
    }
)
_SENSITIVE_LABEL_TERMS = (
    "salary", "compensation", "ctc", "gender", "race", "ethnicity",
    "disability", "veteran", "criminal", "conviction", "citizenship",
    "work authorization", "sponsorship", "relocate",
)


class FieldLayoutFallback(Protocol):
    def resolve_candidate_key(self, label: str, candidate: dict) -> str | None: ...


class OllamaLayoutFallback:
    """Map an unknown label to one known, non-sensitive candidate key."""

    def resolve_candidate_key(self, label: str, candidate: dict) -> str | None:
        normalized_label = " ".join((label or "").lower().split())
        if not normalized_label or any(term in normalized_label for term in _SENSITIVE_LABEL_TERMS):
            return None

        allowed_keys = sorted(
            key for key, value in candidate.items()
            if key in _SAFE_CANDIDATE_KEYS and str(value).strip()
        )
        if not allowed_keys:
            return None

        prompt = (
            "Map this web-form label to exactly one candidate key, or null. "
            "Do not infer a value and do not map sensitive legal, demographic, "
            "or compensation questions. Return JSON only: "
            '{"candidate_key": "one listed key or null"}.\n'
            f"Label: {label!r}\nAllowed keys: {allowed_keys!r}"
        )
        try:
            response = generate_json(prompt)
        except Exception:
            return None
        key = response.get("candidate_key") if isinstance(response, dict) else None
        return key if key in allowed_keys else None
