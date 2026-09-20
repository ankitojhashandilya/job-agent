"""Privacy-safe application-run persistence and measurable success reporting."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from config import APPLICATION_RUNS_JSON, PROJECT_DIR

METRICS_PATH = PROJECT_DIR / "application_metrics.json"


def load_runs(path: Path = APPLICATION_RUNS_JSON) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def append_run(run: dict[str, Any], path: Path = APPLICATION_RUNS_JSON) -> dict[str, Any]:
    """Append one diagnostic run without storing candidate answers."""
    record = dict(run)
    record.setdefault("recorded_at", datetime.now().isoformat(timespec="seconds"))
    runs = load_runs(path)
    runs.append(record)
    path.write_text(json.dumps(runs, indent=2), encoding="utf-8")
    return record


def build_metrics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the verified pre-submit success rate overall and by ATS."""
    eligible = [run for run in runs if run.get("eligible", False)]

    def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        states = Counter(str(item.get("status", "unknown")) for item in items)
        review_ready = sum(
            1
            for item in items
            if item.get("status") == "review_ready"
            and bool((item.get("evidence") or {}).get("verified"))
        )
        total = len(items)
        return {
            "eligible_applications": total,
            "review_ready": review_ready,
            "login_required": states["login_required"],
            "captcha_detected": states["captcha_detected"],
            "manual_required": states["manual_required"] + states["unsupported"],
            "failed": states["failed"] + states["verification_failed"],
            "verified_review_ready_rate": round(review_ready / total * 100, 1) if total else 0.0,
            "states": dict(sorted(states.items())),
        }

    by_ats: dict[str, dict[str, Any]] = {}
    for ats in sorted({str(run.get("ats", "unknown")) for run in eligible}):
        by_ats[ats] = summary([run for run in eligible if str(run.get("ats", "unknown")) == ats])
    return {"overall": summary(eligible), "by_ats": by_ats}


def write_metrics(
    runs_path: Path = APPLICATION_RUNS_JSON,
    destination: Path = METRICS_PATH,
) -> dict[str, Any]:
    report = build_metrics(load_runs(runs_path))
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    print(json.dumps(write_metrics(), indent=2))


if __name__ == "__main__":
    main()
