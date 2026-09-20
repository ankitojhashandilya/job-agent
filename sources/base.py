"""Abstract plugin contract for the canonical job-source interface.

The contract is intentionally website-agnostic: it contains no scraping
logic, no Playwright, no CSS selectors, no browser automation, and no
reference to any specific website. A concrete source (LinkedIn, Indeed,
Naukri, ATS API, company career page, ...) subclasses :class:`JobSource`:

1. Declares a :class:`SourceInfo` describing its capabilities.
2. Implements :meth:`JobSource.search` returning canonical
   :class:`core.models.Job` instances only.
3. Implements :meth:`JobSource.normalize` converting a
   :class:`sources.raw.RawJob` into a canonical :class:`Job`.

The rest of the system never sees raw data — only canonical ``Job``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.models import Job
from sources.raw import RawJob


@dataclass(frozen=True)
class SourceInfo:
    """Static, declarative capabilities of a job source.

    This metadata describes what a source can do and how it should be
    scheduled. It is used by the :class:`SourceManager` to choose which
    sources run for a given discovery request.
    """

    #: Unique slug identifying this source (ex. ``"linkedin"``).
    name: str

    #: Whether the source can filter results by remote work.
    supports_remote: bool = False

    #: Whether the source can search by location.
    supports_location: bool = False

    #: Whether the source supports a salary filter.
    supports_salary_filter: bool = False

    #: Whether the source requires the user to be logged in.
    requires_login: bool = False

    #: Whether the source offers an Easy-Apply-style workflow.
    supports_easy_apply: bool = False

    #: Requests per second / per interval this source tolerates (0 = unknown).
    rate_limit: int = 0

    #: Sort priority. Lower value = queried first. Plugins may set freely.
    priority: int = 100


class JobSource(ABC):
    """Abstract contract every job source plugin must implement."""

    #: Static capability metadata. Concrete sources override this.
    info: SourceInfo

    def __init__(self) -> None:
        """Initialize the source as enabled.

        ``enabled`` is runtime state (toggleable via the registry), distinct
        from the declarative ``info`` metadata.
        """
        self.enabled = True

    @property
    def name(self) -> str:
        """Return the source slug from its :class:`SourceInfo`."""
        return self.info.name

    @abstractmethod
    def search(self, **kwargs: Any) -> list[Job]:
        """Discover jobs from this source.

        Concrete plugins must implement this and return *only* canonical
        :class:`Job` instances. A plugin is expected to use
        :meth:`normalize` internally to convert its raw fetch results.

        Args:
            **kwargs: Source-specific search parameters (keywords,
                location, limit, filters, ...).

        Returns:
            A list of canonical :class:`Job` objects.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement search()."
        )

    @abstractmethod
    def normalize(self, raw_job: RawJob) -> Job:
        """Convert a raw record into a canonical :class:`Job`.

        This is the most important method in the contract. It maps the
        website-shaped :class:`RawJob` into the canonical, source-agnostic
        model so that downstream code never cares which website produced
        the job. The default implementation offers a best-effort mapping
        through :meth:`_canonicalize`; plugins may override it for source
        specific extraction, but must always return a canonical ``Job``.

        Args:
            raw_job: The raw record as emitted by the fetch layer.

        Returns:
            A canonical :class:`core.models.Job` instance.
        """
        return self._canonicalize(raw_job)

    def enrich(self, job: Job) -> Job:
        """Enrich a discovered job with additional details.

        Optional. Concrete plugins override this to pull extra fields such
        as salary, benefits, employment type, recruiter, or company size.
        The default implementation is a pass-through returning the job
        unchanged.

        Args:
            job: The canonical job to enrich.

        Returns:
            The (possibly enriched) canonical job. Returning ``None`` is
            reserved for signalling "this source cannot find the job".
        """
        return job

    def _canonicalize(self, raw_job: RawJob) -> Job:
        """Best-effort mapping of a :class:`RawJob` to a canonical :class:`Job`.

        Args:
            raw_job: The raw source record.

        Returns:
            A canonical :class:`Job` carrying the raw payload verbatim.
        """
        data = {
            "title": raw_job.title,
            "company": raw_job.company,
            "location": raw_job.location,
            "url": raw_job.url,
            "source": raw_job.source_name or self.name,
            "source_job_id": raw_job.data.get("id") or raw_job.data.get("job_id"),
            "description": raw_job.description
            or str(raw_job.data.get("description") or ""),
        }
        job = Job.from_dict(data)
        job.raw = dict(raw_job.data)
        return job

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<JobSource name={self.name!r}>"


__all__ = ["JobSource", "SourceInfo"]