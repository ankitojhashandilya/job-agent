# discovery.py

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from config import JOB_RESULTS_CSV, JOB_RESULTS_JSON
from job_history import update_job_history
from scorer import score_job
from sources import DiscoveryEngine, SourceManager, SourceRegistry

# These JSON/CSV files are EXPORT views of job_results — snapshots of a
# run, not the system of record. The authoritative incremental history
# lives in job_history.json. Exports are regenerated on every run.
EXPORT_KIND = "job_results"
EXPORT_SYSTEM_OF_RECORD = "job_history.json"


PROJECT_DIR = Path(__file__).resolve().parent

RESULTS_COLUMNS = [
    "company",
    "title",
    "location",
    "url",
    "search_keyword",
    "match_score",
    "status",
    "reason",
    "matched_skills",
    "missing_skills",
    "technical_fit",
    "seniority",
    "leadership",
    "location_fit",
    "domain_fit",
    "growth_fit",
]


def run_discovery(
    keywords: list[str] | None = None,
    location: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Discover, score, and persist jobs via the plugin architecture.

    This is the new pipeline entry point. It replaces the legacy
    ``linkedin_score_jobs.py`` stage, running through the
    ``DiscoveryEngine -> SourceManager -> Registry -> Plugin`` stack and
    producing the same ``job_results.json`` / ``job_results.csv`` output.

    Args:
        keywords: Search keywords (optional; sources use defaults).
        location: Optional location filter.
        limit: Optional per-source cap.

    Returns:
        The list of scored job result dicts that was persisted.
    """
    registry = SourceRegistry().discover(package="sources")
    manager = SourceManager(registry)
    engine = DiscoveryEngine(manager)

    jobs = engine.discover(
        keywords=keywords,
        location=location,
        limit=limit,
    )

    if not jobs and manager.last_errors:
        details = "; ".join(
            f"{source}: {message}" for source, message in manager.last_errors.items()
        )
        raise RuntimeError(f"All enabled discovery sources failed. {details}")

    results: list[dict] = []
    for job in jobs:
        summary = job.to_dict()
        scoring = score_job(summary)
        record = {
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "url": job.url,
            "search_keyword": job.raw.get("search_keyword", ""),
            "description": job.description,
            "match_score": scoring["score"],
            "status": scoring["status"],
            "reason": scoring["reason"],
            "matched_skills": scoring.get("matched_skills", []),
            "missing_skills": scoring.get("missing_skills", []),
            "subscores": scoring.get("subscores", {}),
        }
        results.append(record)
        update_job_history(record, record["status"], "discovery")
        _persist(results)

    _persist(results)
    print(
        f"Saved {len(results)} jobs to "
        f"{JOB_RESULTS_JSON} and {JOB_RESULTS_CSV}"
    )
    return results


def _persist(results: list[dict]) -> None:
    """Write results to the export JSON and CSV outputs.

    The ``job_results.json`` / ``job_results.csv`` files are *exports* —
    regenerated snapshots of a run, not the system of record (that is
    ``job_history.json``). A companion ``job_results.export.json`` labels
    the export so no consumer mistakes it for authoritative storage.
    """
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Export label — companion metadata, keeps the existing JSON/CSV
    # formats byte-for-byte compatible with all current consumers.
    JOB_RESULTS_JSON.with_name("job_results.export.json").write_text(
        json.dumps(
            {
                "_export": True,
                "kind": EXPORT_KIND,
                "system_of_record": EXPORT_SYSTEM_OF_RECORD,
                "generated_at": generated_at,
                "files": ["job_results.json", "job_results.csv"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    JOB_RESULTS_JSON.write_text(
        json.dumps(results, indent=2),
        encoding="utf-8",
    )

    with JOB_RESULTS_CSV.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=RESULTS_COLUMNS)
        writer.writeheader()

        for result in results:
            row = {key: result.get(key, "") for key in RESULTS_COLUMNS}

            row["matched_skills"] = ", ".join(
                result.get("matched_skills", [])
            )
            row["missing_skills"] = ", ".join(
                result.get("missing_skills", [])
            )

            subscores = result.get("subscores", {})
            row["technical_fit"] = subscores.get("technical_fit", 0)
            row["seniority"] = subscores.get("seniority", 0)
            row["leadership"] = subscores.get("leadership", 0)
            row["location_fit"] = subscores.get("location", 0)
            row["domain_fit"] = subscores.get("domain", 0)
            row["growth_fit"] = subscores.get("growth", 0)

            writer.writerow(row)


def main() -> None:
    run_discovery()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nDiscovery interrupted by user.")
    except Exception as error:
        print(f"\n\nDiscovery failed:\n{error}")
        raise
