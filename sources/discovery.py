"""Orchestration layer for multi-source job discovery.

``DiscoveryEngine`` sits between the pipeline and :class:`SourceManager`.
It is responsible for running all enabled sources, merging their results,
de-duplicating by the canonical stable key, and sorting before emitting
the final collection of canonical :class:`core.models.Job` objects.

Keeping this orchestration here (rather than inside ``SourceManager``)
means ``SourceManager`` stays focused on a single-call search, while
``DiscoveryEngine`` owns the cross-source workflow the pipeline calls:
    Pipeline -> DiscoveryEngine -> SourceManager -> Registry -> Plugins
"""

from __future__ import annotations

from typing import Any, Callable

from core.models import Job
from sources.manager import SourceManager

SortKey = Callable[[Job], Any]


class DiscoveryEngine:
    """Runs discovery across sources and returns canonocal, de-duplicated jobs.

    Attributes:
        manager: The :class:`SourceManager` that executes per-source searches.
    """

    def __init__(self, manager: SourceManager) -> None:
        """Initialize the engine with injected dependencies.

        Args:
            manager: The source manager used to run searches.
        """
        self.manager = manager

    def discover(
        self,
        keywords: list[str] | str | None = None,
        location: str | None = None,
limit: int | None = None,
        sort_key: SortKey | None = None,
        reverse: bool = False,
        **kwargs: Any,
    ) -> list[Job]:
        """Run discovery across all enabled sources.

        Merges, de-duplicates, optionally sorts, and emits canonical jobs.

        Args:
            keywords: One or more search keywords passed to each source.
            location: Optional location filter.
            limit: Optional cap on returned jobs.
            sort_key: Optional callable producing a sort key per job.
            reverse: Whether to sort in descending order (with ``sort_key``).
            **kwargs: Additional source-specific parameters.

        Returns:
            Merged, de-duplicated, optionally sorted canonical jobs.
        """
        jobs = self.manager.search(
            keywords=keywords,
            location=location,
            limit=limit,
            **kwargs,
        )
        jobs = _deduplicate(jobs)
        if sort_key is not None:
            jobs = sorted(jobs, key=sort_key, reverse=reverse)
        return jobs


def _deduplicate(jobs: list[Job]) -> list[Job]:
    """Remove jobs sharing the same stable key, keeping the first.

    Args:
        jobs: Jobs possibly containing duplicates across sources.

    Returns:
        De-duplicated jobs in first-encounter order.
    """
    seen: set[str] = set()
    unique: list[Job] = []
    for job in jobs:
        key = job.stable_key
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


__all__ = ["DiscoveryEngine", "SortKey"]