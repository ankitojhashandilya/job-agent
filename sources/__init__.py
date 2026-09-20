"""Pluggable job-source discovery.

The ``sources`` package defines the plugin contract every job source must
implement (``JobSource`` + ``SourceInfo``), the raw record model
(``RawJob``), the plugin management and auto-discovery (`SourceRegistry`),
and the orchestration layer (`SourceManager`) that runs searches across all
registered plugins and returns canonical :class:`core.models.Job` objects.
"""

from sources.base import JobSource, SourceInfo
from sources.discovery import DiscoveryEngine
from sources.manager import SourceManager
from sources.raw import RawJob
from sources.registry import (
    SourceRegistry,
    discover,
    register,
    registry,
)

__all__ = [
    "JobSource",
    "SourceInfo",
    "RawJob",
    "SourceRegistry",
    "SourceManager",
    "DiscoveryEngine",
    "registry",
    "register",
    "discover",
]