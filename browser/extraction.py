"""Read-only DOM extraction helpers shared between legacy and agent code.

Every function in this module inspects the page without modifying it.
These are the building blocks for both the legacy apply_top_jobs.py
workflows and the new AI agent's perception layer.
"""

from __future__ import annotations

from urllib.parse import urlparse

from playwright.sync_api import Locator, Page


def label_text_for_input(field: Locator) -> str:
    """Extract the human-readable label for a form input element.

    Tries, in order:
    1. aria-label attribute
    2. placeholder attribute
    3. Associated <label for="..."> element

    Args:
        field: A Playwright Locator pointing to a single form element.

    Returns:
        The label text, or empty string if none could be determined.
    """

    try:
        aria = field.get_attribute("aria-label", timeout=1000)
        if aria:
            return aria
    except Exception:
        pass

    try:
        placeholder = field.get_attribute("placeholder", timeout=1000)
        if placeholder:
            return placeholder
    except Exception:
        pass

    try:
        field_id = field.get_attribute("id", timeout=1000)
        if field_id:
            page = field.page
            label = page.locator(f'label[for="{field_id}"]').first
            if label.count():
                return label.inner_text(timeout=1000)
    except Exception:
        pass

    return ""


def classify_page_state(page: Page) -> str:
    """Classify the current page into a high-level state.

    Args:
        page: A Playwright page object.

    Returns:
        One of:
            "account_required"       — login/sign-in wall visible.
            "job_unavailable"        — job posting no longer exists.
            "job_apply_redirect_lost" — redirected to a dead end.
            "open"                   — page is accessible.
            "unknown"                — could not determine state.
    """

    try:
        text = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        return "unknown"

    if any(
        needle in text
        for needle in ["sign in", "login", "log in", "create account"]
    ):
        return "account_required"

    if any(
        needle in text
        for needle in [
            "job no longer available",
            "position has been filled",
        ]
    ):
        return "job_unavailable"

    if "join the atlassian talent community" in text:
        return "job_apply_redirect_lost"

    return "open"


def current_domain(page: Page) -> str:
    """Extract the domain (netloc) from the current page URL.

    Args:
        page: A Playwright page object.

    Returns:
        The domain string (e.g. "boards.greenhouse.io"),
        or empty string if the URL is not accessible.
    """

    try:
        return urlparse(page.url).netloc
    except Exception:
        return ""
