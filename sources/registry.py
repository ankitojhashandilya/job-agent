"""Registry and plugin auto-discovery for job-source plugins.

The registry is a website-agnostic container: it keys sources by their
``name`` and knows nothing about their internals or which websites they
target. It also provides plugin auto-discovery via ``pkgutil`` /
``importlib`` so a plugin file dropped under the ``sources`` package is
picked up automatically, with no manual registration call.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Iterator

from sources.base import JobSource

#: Modules in the sources package that are architecture, not plugins.
BUILTIN_MODULES = frozenset({"base", "registry", "manager", "raw"})

logger = logging.getLogger(__name__)


class SourceRegistry:
    """Manages a set of :class:`JobSource` plugins by name.

    Supports registration, lookup, enable/disable toggling, iteration, and
    automatic plugin discovery from the ``sources`` package. The registry
    contains no website-specific logic and never inspects source internals.
    """

    def __init__(self, sources: list[JobSource] | None = None) -> None:
        """Initialize the registry.

        Args:
            sources: Optional initial sources to register immediately.
        """
        self._sources: dict[str, JobSource] = {}
        for source in sources or []:
            self.register(source)

    def register(self, source: JobSource) -> JobSource:
        """Register a source, keyed by its ``name``.

        Registering a source with an already-registered name replaces the
        previous entry. An empty (or missing) name is rejected.

        Args:
            source: The source plugin to register.

        Returns:
            The registered source (useful for chaining or decorator use).

        Raises:
            ValueError: If ``source.name`` is empty.
        """
        name = getattr(source, "name", "")
        if not name:
            raise ValueError("A JobSource must define a non-empty 'name'.")
        self._sources[name] = source
        return source

    def get(self, name: str) -> JobSource | None:
        """Return a registered source by name, or ``None`` if absent.

        Args:
            name: The source slug to look up.

        Returns:
            The source, or ``None`` when not registered.
        """
        return self._sources.get(name)

    def remove(self, name: str) -> None:
        """Unregister a source by name (no-op if absent).

        Args:
            name: The source slug to remove.
        """
        self._sources.pop(name, None)

    def enable(self, name: str) -> None:
        """Enable a registered source for discovery.

        Args:
            name: The source slug to enable.

        Raises:
            KeyError: If the source is not registered.
        """
        self._sources[name].enabled = True

    def disable(self, name: str) -> None:
        """Disable a registered source without removing it.

        Args:
            name: The source slug to disable.

        Raises:
            KeyError: If the source is not registered.
        """
        self._sources[name].enabled = False

    def active_sources(self) -> list[JobSource]:
        """Return all registered sources that are currently enabled.

        Results are sorted by (:attr:`SourceInfo.priority`, name) so high
        priority sources run first.

        Returns:
            The list of enabled :class:`JobSource` instances.
        """
        return sorted(
            (
                source
                for source in self._sources.values()
                if getattr(source, "enabled", True)
            ),
            key=lambda source: (getattr(source.info, "priority", 100), source.name),
        )

    def discover(self, package: str = "sources") -> SourceRegistry:
        """Auto-discover and register every concrete plugin in ``package``.

        Scans the package using ``pkgutil`` and ``inspect``, importing each
        module. Any non-abstract class that subclasses :class:`JobSource`
        is instantiated and registered. Architecture modules are skipped.

        Args:
            package: Dotted package name to scan (default ``"sources"``).

        Returns:
            ``self``, the registry, for chaining.
        """
        root = importlib.import_module(package)
        for _, module_name, _ in pkgutil.iter_modules(root.__path__):
            if module_name in BUILTIN_MODULES:
                continue
            full = f"{package}.{module_name}"
            try:
                module = importlib.import_module(full)
            except Exception as error:  # pragma: no cover - depends on env
                logger.warning("Could not import plugin %s: %s", full, error)
                continue
            for _, attribute in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(attribute, JobSource)
                    and attribute is not JobSource
                    and not inspect.isabstract(attribute)
                ):
                    plugin = attribute()
                    self.register(plugin)
                    logger.info("discovered source %r from %s", plugin.name, full)
        return self

    def reload(self, package: str = "sources") -> SourceRegistry:
        """Re-run discovery, replacing the current plugin set.

        Existing manually-registered sources are preserved; any discovered
        name that was not explicitly registered is cleared before re-scanning.

        Args:
            package: Dotted package name to scan.

        Returns:
            ``self``, for chaining.
        """
        preserved = list(self._sources.values())
        self._sources = {}
        for source in preserved:
            self.register(source)
        self.discover(package)
        return self

    def __iter__(self) -> Iterator[JobSource]:
        """Iterate over registered sources in insertion order."""
        return iter(self._sources.values())

    def __len__(self) -> int:
        """Return the number of registered sources."""
        return len(self._sources)

    def __contains__(self, name: str) -> bool:
        """Return whether a source named ``name`` is registered."""
        return name in self._sources


_default_registry: SourceRegistry = SourceRegistry()
registry: SourceRegistry = _default_registry


def register(source: JobSource) -> JobSource:
    """Register a source on the default module-level registry.

    Args:
        source: The source plugin to register.

    Returns:
        The registered source.
    """
    return _default_registry.register(source)


def discover(package: str = "sources") -> SourceRegistry:
    """Auto-discover plugins into the default registry.

    Args:
        package: Dotted package name to scan.

    Returns:
        The default registry.
    """
    return _default_registry.discover(package)


__all__ = ["SourceRegistry", "registry", "register", "discover"]