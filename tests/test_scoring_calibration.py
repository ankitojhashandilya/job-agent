"""Regression tests for the deterministic scoring calibration."""

from unittest.mock import patch

import scorer


def test_validate_response_preserves_original_job_context():
    job = {
        "title": "Principal Data Engineer",
        "description": "Own a cloud data platform.",
        "location": "Bengaluru, India",
    }

    with patch("scorer.ScoreCalculator") as calculator_type:
        calculator_type.return_value.calculate.return_value = {
            "score": 76,
            "status": "Apply",
            "reason": "Strong fit",
            "matched_skills": ["Python"],
            "missing_skills": [],
            "subscores": {},
        }
        result = scorer.validate_response(
            {"matched_skills": ["Python"], "missing_skills": [], "reason": "Strong fit"},
            job,
        )

    assert result["status"] == "Apply"
    assert calculator_type.return_value.calculate.call_args.kwargs["job"] == job
