"""Shared browser utilities for the job-agent project.

This package contains read-only DOM extraction helpers shared
between the legacy Playwright scripts and the new AI agent.
"""

from browser.extraction import (
    classify_page_state,
    current_domain,
    label_text_for_input,
)

__all__ = [
    "classify_page_state",
    "current_domain",
    "label_text_for_input",
]
