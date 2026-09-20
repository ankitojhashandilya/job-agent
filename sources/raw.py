"""Raw, un-normalised records as emitted by a source's fetch layer.

A :class:`RawJob` is the untouched, website-shaped representation of a
job before any normalisation happens. Its purpose is to make debugging
easy: the raw data is preserved verbatim, exactly as the website/API
returned it, so nothing is lost between discovery and normalisation.

The normalisation step (:meth:`JobSource.normalize`) consumes a
``RawJob`` and produces a canonical :class:`core.models.Job`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Field name aliases understood by the shared canonicalisation helper.
# Keys are the canonical field; values are known raw field spellings.
KNOWN_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "job_title", "jobTitle", "name", "role"),
    "company": ("company", "company_name", "companyName", "org"),
    "location": ("location", "job_location", "jobLocation", "city"),
    "url": ("url", "job_url", "jobUrl", "apply_url", "applyUrl", "link"),
    "description": (
        "description",
        "job_description",
        "jobDescription",
        "summary",
        "body",
    ),
}


@dataclass
class RawJob:
    """Unmodified record as fetched from a job source.

    ``data`` holds the complete raw payload (which may contain anything a
    source returns — fields, arrays, nested objects). The structured
    attributes (``title``, ``company``, ...) are convenience mirrors of
    the most common fields so that plugins and debuggers can read them
    without reaching into the opaque ``data`` dict. They may be empty if
    the source only exposes fields through ``data``.

    Attributes:
        source_name: Slug of the source that produced this record.
        data: The full, unmodified raw payload from the source.
        title: Convenience mirror of the posting title (may be "").
        company: Convenience mirror of the company name (may be "").
        location: Convenience mirror of the location (may be "").
        url: Convenience mirror of the posting URL (may be "").
        description: Convenience mirror of the description text (may be "").
        fetched_at: ISO 8601 timestamp of when the record was fetched.
    """

    source_name: str
    data: dict[str, Any] = field(default_factory=dict)
    url: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    fetched_at: str = ""

    @classmethod
    def from_raw(
        cls,
        data: dict[str, Any],
        source_name: str = "",
    ) -> RawJob:
        """Build a ``RawJob`` from an arbitrary source payload.

        Common field names are extracted from the payload using sensible
        aliases, so plugins can rely on the structured attributes being
        populated when a source uses standard keys.

        Args:
            data: The raw dict returned by a source's fetch layer.
            source_name: Slug of the producing source.

        Returns:
            A populated :class:`RawJob`.
        """
        return cls(
            source_name=source_name,
            data=dict(data),
            title=_pick(data, KNOWN_ALIASES["title"]),
            company=_pick(data, KNOWN_ALIASES["company"]),
            location=_pick(data, KNOWN_ALIASES["location"]),
            url=_pick(data, KNOWN_ALIASES["url"]),
            description=_pick(data, KNOWN_ALIASES["description"]),
            fetched_at=datetime.now().isoformat(timespec="seconds"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a dict describing this raw record (for debugging/logs)."""
        return {
            "source_name": self.source_name,
            "url": self.url,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "description": self.description,
            "data": self.data,
            "fetched_at": self.fetched_at,
        }


def _pick(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Return the first non-empty string value among ``keys``.

    Args:
        data: The raw payload to search.
        keys: Candidate field names, in priority order.

    Returns:
        The matching value, or ``""`` if none is present/non-empty.
    """
    for key in keys:
        if key in data and data[key]:
            return str(data[key])
    return ""


__all__ = ["RawJob", "KNOWN_ALIASES"]