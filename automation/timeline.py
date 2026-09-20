"""Timeline recorder — chronological event log for an application run.

The engine records lifecycle events here (Observe Page, Extract Tasks,
Resolve, Filled, Verified, Clicked Continue, Resume Uploaded, Planner
Retry, Completed). The recorder is pure and injectable — it appends
:class:`TimelineEvent` values and can dump them to ``timeline.json``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from automation.types import TimelineEvent

# Canonical event types.
EVENT_OBSERVE = "Observe Page"
EVENT_EXTRACT = "Extract Tasks"
EVENT_RESOLVE = "Resolve"
EVENT_FILL = "Filled"
EVENT_VERIFY = "Verified"
EVENT_CLICK = "Clicked Continue"
EVENT_UPLOAD = "Resume Uploaded"
EVENT_RETRY = "Planner Retry"
EVENT_COMPLETE = "Completed"


class Timeline:
    """Appends and serializes application timeline events.

    Attributes:
        events: The ordered list of recorded events.
    """

    def __init__(self) -> None:
        """Initialize an empty timeline."""
        self.events: list[TimelineEvent] = []

    def record(
        self,
        event_type: str,
        detail: str = "",
        timestamp: str | None = None,
    ) -> TimelineEvent:
        """Append a new event to the timeline.

        Args:
            event_type: The canonical event type label.
            detail: Human-readable detail for the event.
            timestamp: ISO timestamp (defaults to now, UTC).

        Returns:
            The newly appended :class:`TimelineEvent`.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        event = TimelineEvent(
            sequence=len(self.events) + 1,
            event_type=event_type,
            timestamp=timestamp,
            detail=detail,
        )
        self.events.append(event)
        return event

    def extend(self, events: Iterable[TimelineEvent]) -> None:
        """Append pre-built events, preserving sequence order.

        Args:
            events: An iterable of :class:`TimelineEvent` to append.
        """
        base = len(self.events)
        for offset, event in enumerate(events):
            self.events.append(
                TimelineEvent(
                    sequence=base + offset + 1,
                    event_type=event.event_type,
                    timestamp=event.timestamp,
                    detail=event.detail,
                )
            )

    def to_dicts(self) -> list[dict[str, object]]:
        """Serialize all events to JSON-compatible dicts."""
        return [event.to_dict() for event in self.events]

    def write(self, path: str | Path) -> Path:
        """Write the timeline to a JSON file.

        Args:
            path: Destination path for ``timeline.json``.

        Returns:
            The path written.
        """
        destination = Path(path)
        payload = {
            "events": self.to_dicts(),
            "total": len(self.events),
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return destination


__all__ = [
    "Timeline",
    "TimelineEvent",
    "EVENT_OBSERVE",
    "EVENT_EXTRACT",
    "EVENT_RESOLVE",
    "EVENT_FILL",
    "EVENT_VERIFY",
    "EVENT_CLICK",
    "EVENT_UPLOAD",
    "EVENT_RETRY",
    "EVENT_COMPLETE",
]
