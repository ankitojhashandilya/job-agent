import json
from datetime import datetime

from config import JOB_HISTORY_JSON


def load_history() -> dict:
    if not JOB_HISTORY_JSON.exists():
        return {}

    return json.loads(
        JOB_HISTORY_JSON.read_text(
            encoding="utf-8"
        )
    )


def save_history(history: dict) -> None:
    JOB_HISTORY_JSON.write_text(
        json.dumps(history, indent=2),
        encoding="utf-8",
    )


def update_job_history(job: dict, status: str, source: str) -> None:
    history = load_history()
    url = job.get("url")

    if not url:
        return

    existing = history.get(url, {})

    history[url] = {
        **existing,
        "company": job.get("company", existing.get("company", "")),
        "title": job.get("title", existing.get("title", "")),
        "location": job.get("location", existing.get("location", "")),
        "url": url,
        "last_status": status,
        "last_source": source,
        "last_seen_at": datetime.now().isoformat(timespec="seconds"),
    }

    save_history(history)


def already_applied_or_ready(url: str) -> bool:
    history = load_history()
    status = history.get(url, {}).get("last_status", "")

    return status in {
        "ready_for_review",
        "submitted",
        "SUBMITTED",
        "READY_FOR_REVIEW",
    }
