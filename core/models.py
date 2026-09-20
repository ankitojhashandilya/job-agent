"""Core domain models for the job agent.

This module defines the canonical ``Job`` and ``Application`` models that
all other layers (sources, ats, memory, scoring) share.  Both models
map round-trip to and from the plain ``dict`` payloads the existing
pipeline scripts already read and write, so adopting them never forces
a rewrite of existing code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class Job:
    """A single job posting discovered from any source.

    Attributes:
        title: Public job title from the posting.
        company: Company posting the listing.
        location: Free-text location (ex. "Bangalore, India").
        url: Canonical URL of the posting.
        source: Source slug (ex. "linkedin", "indeed").
        source_job_id: Source-specific job identifier, if available.
            Prefer this over ``url`` for deduplication: URLs can change.
        description: Full description text when available.
        raw: Any extra metadata a source provides beyond the core fields.
    """

    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    source: str = ""
    source_job_id: str = ""
    description: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Job:
        """Build a ``Job`` from a pipeline-style dict, tolerating alias keys."""
        return cls(
            title=str(data.get("title") or data.get("job_title") or ""),
            company=str(data.get("company") or ""),
            location=str(data.get("location") or data.get("job_location") or ""),
            url=str(data.get("url") or ""),
            source=str(data.get("source") or ""),
            source_job_id=str(
                data.get("source_job_id")
                or data.get("source_id")
                or data.get("job_id")
                or ""
            ),
            description=str(data.get("description") or data.get("job_description") or ""),
            raw=dict(data.get("raw") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a dict matching the shape existing pipeline scripts expect."""
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "source": self.source,
            "source_job_id": self.source_job_id,
            "description": self.description,
            "raw": self.raw,
        }

    @property
    def stable_key(self) -> str:
        """Return the URL as the stable deduplication key."""
        return self.url


@dataclass
class Application:
    """A record of one application attempt for a job.

    Attributes:
        job: The job this application is for.
        timestamp: ISO 8601 timestamp of the attempt.
        match_score: Normalized 0-100 score at apply time.
        apply_type: How the application was performed (ex. "easy_apply").
        apply_url: Final page URL reached during the attempt.
        status: Lifecycle status string (ex. "READY_FOR_REVIEW").
        resume_uploaded: Whether the resume was uploaded.
        fields_filled: Names of form fields populated during the attempt.
        screenshot: Path to the captured screenshot, if any.
        notes: Free-text notes from the apply stage.
    """

    job: Job = field(default_factory=Job)
    timestamp: str = ""
    company_name: str = ""
    match_score: int = 0
    apply_type: str = ""
    apply_url: str = ""
    status: str = ""
    resume_uploaded: bool = False
    fields_filled: list[str] = field(default_factory=list)
    screenshot: str = ""
    notes: str = ""

    @classmethod
    def from_record(cls, data: Mapping[str, Any]) -> Application:
        """Build an ``Application`` from an ``apply_top_jobs`` record dict."""
        return cls(
            job=Job.from_dict(data),
            timestamp=str(data.get("timestamp") or ""),
            company_name=str(data.get("company") or ""),
            match_score=int(data.get("match_score", 0) or 0),
            apply_type=str(data.get("apply_type") or ""),
            apply_url=str(data.get("apply_url") or ""),
            status=str(data.get("status") or ""),
            resume_uploaded=bool(data.get("resume_uploaded", False)),
            fields_filled=[str(f) for f in data.get("fields_filled", []) or []],
            screenshot=str(data.get("screenshot") or ""),
            notes=str(data.get("notes") or ""),
        )

    def to_record(self) -> dict[str, Any]:
        """Return a dict matching the applications-record schema."""
        return {
            "timestamp": self.timestamp,
            "company": self.company_name or self.job.company,
            "title": self.job.title,
            "location": self.job.location,
            "url": self.job.url,
            "match_score": self.match_score,
            "apply_type": self.apply_type,
            "apply_url": self.apply_url,
            "status": self.status,
            "resume_uploaded": self.resume_uploaded,
            "fields_filled": self.fields_filled,
            "screenshot": self.screenshot,
            "notes": self.notes,
        }


__all__ = ["Job", "Application"]