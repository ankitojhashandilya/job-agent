"""Recalculate discovered-job scores from their recorded LLM analysis.

This is deliberately offline: it does not browse or call Ollama.  It is the
safe way to apply scoring-rule changes to ``job_results.json`` before deciding
whether any live job is eligible for browser automation.
"""

from __future__ import annotations

import csv
import json

from agent.scoring import ScoreCalculator
from config import JOB_RESULTS_CSV, JOB_RESULTS_JSON


def main() -> None:
    if not JOB_RESULTS_JSON.exists():
        raise FileNotFoundError(f"No discovered jobs found at {JOB_RESULTS_JSON}")

    jobs = json.loads(JOB_RESULTS_JSON.read_text(encoding="utf-8"))
    if not isinstance(jobs, list):
        raise ValueError("job_results.json must contain a list of jobs")

    calculator = ScoreCalculator()
    counts: dict[str, int] = {"Apply": 0, "Review": 0, "Maybe": 0, "Reject": 0}
    rows: list[dict] = []

    for job in jobs:
        scoring = calculator.calculate(
            {
                "matched_skills": job.get("matched_skills", []),
                "missing_skills": job.get("missing_skills", []),
                "reason": job.get("reason", ""),
            },
            job,
        )
        job.update(
            {
                "match_score": scoring["score"],
                "status": scoring["status"],
                "reason": scoring["reason"],
                "matched_skills": scoring["matched_skills"],
                "missing_skills": scoring["missing_skills"],
                "subscores": scoring["subscores"],
            }
        )
        counts[scoring["status"]] = counts.get(scoring["status"], 0) + 1
        rows.append(job)

    JOB_RESULTS_JSON.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    columns = [
        "company", "title", "location", "url", "search_keyword", "match_score",
        "status", "reason", "matched_skills", "missing_skills", "technical_fit",
        "seniority", "leadership", "location_fit", "domain_fit", "growth_fit",
    ]
    with JOB_RESULTS_CSV.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for job in rows:
            subscores = job.get("subscores", {})
            writer.writerow(
                {
                    **{field: job.get(field, "") for field in columns},
                    "matched_skills": ", ".join(job.get("matched_skills", [])),
                    "missing_skills": ", ".join(job.get("missing_skills", [])),
                    "technical_fit": subscores.get("technical_fit", 0),
                    "seniority": subscores.get("seniority", 0),
                    "leadership": subscores.get("leadership", 0),
                    "location_fit": subscores.get("location", 0),
                    "domain_fit": subscores.get("domain", 0),
                    "growth_fit": subscores.get("growth", 0),
                }
            )

    print(f"Recalibrated {len(rows)} jobs without browser or model calls.")
    print(" | ".join(f"{status}: {count}" for status, count in counts.items()))


if __name__ == "__main__":
    main()
