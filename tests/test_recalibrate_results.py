import json

import recalibrate_results


def test_recalibration_updates_scores_without_external_calls(tmp_path, monkeypatch):
    results_path = tmp_path / "job_results.json"
    csv_path = tmp_path / "job_results.csv"
    results_path.write_text(
        json.dumps(
            [
                {
                    "title": "Principal Data Engineer",
                    "description": "Cloud data architecture and mentoring.",
                    "location": "Remote",
                    "matched_skills": ["Python"],
                    "missing_skills": [],
                    "reason": "Good fit",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(recalibrate_results, "JOB_RESULTS_JSON", results_path)
    monkeypatch.setattr(recalibrate_results, "JOB_RESULTS_CSV", csv_path)

    recalibrate_results.main()

    result = json.loads(results_path.read_text(encoding="utf-8"))[0]
    assert isinstance(result["match_score"], int)
    assert result["status"] in {"Apply", "Review", "Maybe", "Reject"}
    assert csv_path.exists()
