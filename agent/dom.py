"""Read-only selection of the active application surface."""

from playwright.sync_api import Locator, Page


def interaction_scope(page: Page) -> Page | Locator:
    """Prefer an open application dialog, then a form inside the main content.

    The surrounding page can contain search boxes, pagination and unrelated
    contact forms. Never include those in an active application dialog.
    """
    for selector in (
        "[role='dialog'], dialog",
        "main form, [role='main'] form",
        "main, [role='main']",
    ):
        try:
            candidates = page.locator(selector)
            for index in range(min(candidates.count(), 30) - 1, -1, -1):
                candidate = candidates.nth(index)
                if candidate.get_attribute("role") == "search":
                    continue
                if (
                    candidate.is_visible()
                    and candidate.locator(
                        "input, textarea, select, button, [role='combobox'], [role='radio']"
                    ).count()
                ):
                    return candidate
        except Exception:
            continue
    return page
