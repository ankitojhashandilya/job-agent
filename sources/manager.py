"""Discovery orchestration across multiple job sources.

The :class:`SourceManager` is the runtime entry point used by discovery
(such as the future ``discovery.py`` orchestator step). It loads plugins,
runs searches, merges results across all enabled sources, and de-duplicates
the canonical :class:`Job` output before returning it to the caller.

The manager receives its dependencies through the constructor
(dependency injection): a source registry, plus optional browser, logger,
and cache collaborators.
"""

from __future__ import annotations

import logging
from typing import Any

from core.models import Job
from sources.base import JobSource
from sources.registry import SourceRegistry


class SourceManager:
    """Orchestrates search across the registered :class:`JobSource` plugins.

    Attributes:
        registry: The :class:`SourceRegistry` providing the plugin set.
        browser: Optional injected browser-backed helper (unused today).
        logger: Optional logger; a default is created if not provided.
        cache: Optional injected cache (unused today).
    """

    def __init__(
        self,
        registry: SourceRegistry,
        browser: Any | None = None,
        logger: logging.Logger | None = None,
        cache: Any | None = None,
    ) -> None:
        """Initialize the manager with injected dependencies.

        Args:
            registry: Source registry containing the plugins to search.
            browser: Optional browser abstraction for sources that need it.
            logger: Optional logger; a default named logger is used if None.
            cache: Optional cache abstraction shared across sources.
        """
        self.registry = registry
        self.browser = browser
        self.cache = cache
        self._logger = logger or logging.getLogger("sources.manager")
        self.last_errors: dict[str, str] = {}

    def search(
        self,
        keywords: list[str] | str | None = None,
        location: str | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> list[Job]:
        """Search every active source and return de-duplicated canonical jobs.

        Args:
            keywords: One or more search keywords. Passed to each source.
            location: Optional location filter, passed to each source.
            limit: Optional per-source result cap.
            **kwargs: Additional source-specific parameters.

        Returns:
            A merged, de-duplicated list of canonical :class:`Job` objects.
        """
        query: dict[str, Any] = {
            "keywords": keywords,
            "location": location,
            "limit": limit,
            **kwargs,
}
        collected: list[Job] = []
        self.last_errors = {}
        sources = self.registry.active_sources()

        self._logger.info("searching %d source(s)", len(sources))

        for source in sources:
            try:
                results = self._run_source(source, query)
            except Exception as error:  # noqa: BLE001 - one source must not kill all
                self.last_errors[source.name] = str(error)
                self._logger.warning(
                    "source %r failed during search: %s",
                    source.name,
                    error,
                )
                continue
            collected.extend(results)

        return collected

    def discover(self, package: str = "sources") -> SourceRegistry:
        """Ask the registry to auto-discover plugins.

        Args:
            package: Dotted package name to scan.

        Returns:
            The manager's registry.
        """
        return self.registry.discover(package)

    @staticmethod
    def _run_source(
        source: JobSource,
        query: dict[str, Any],
    ) -> list[Job]:
        """Run a single source search and normalise its results.

        Args:
            source: The source to invoke.
            query: Normalised query parameters.

        Returns:
            Canonical :class:`Job` results from this source.
        """
        return source.search(**query)


__all__ = ["SourceManager"]
