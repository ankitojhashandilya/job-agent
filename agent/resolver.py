from __future__ import annotations

import hashlib
import re
from typing import Any

from playwright.sync_api import Locator, Page


# ── ID prefix constants ───────────────────────────────────────────

FIELD_PREFIX = "field:"
BUTTON_PREFIX = "button:"
UPLOAD_PREFIX = "upload:"


# ── Pure helpers (no Playwright dependency) ───────────────────────

def slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def element_fingerprint(element: Any, field_type: str) -> str:
    parts: list[str] = [field_type]
    for attr_name in ["name", "id", "class", "placeholder"]:
        try:
            val = element.get_attribute(attr_name)
            if val:
                parts.append(f"{attr_name}={val.strip()}")
        except Exception:
            pass
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()[:7]


def _make_unique_id(candidate_id: str, used_ids: set[str]) -> str:
    if candidate_id not in used_ids:
        return candidate_id
    suffix = 2
    while f"{candidate_id}_{suffix}" in used_ids:
        suffix += 1
    return f"{candidate_id}_{suffix}"


# ── Candidate ID generation (used during observation) ────────────

def _candidate_field_id(element: Any, label: str, field_type: str) -> str:
    if label:
        s = slugify(label)
        if s:
            return f"{FIELD_PREFIX}{s}"
    try:
        name = element.get_attribute("name")
        if name and name.strip():
            s = slugify(name.strip())
            if s:
                return f"{FIELD_PREFIX}{s}"
    except Exception:
        pass
    try:
        elem_id = element.get_attribute("id")
        if elem_id and elem_id.strip():
            s = slugify(elem_id.strip())
            if s:
                return f"{FIELD_PREFIX}{s}"
    except Exception:
        pass
    return f"{FIELD_PREFIX}{element_fingerprint(element, field_type)}"


def _candidate_button_id(button_text: str) -> str:
    if button_text:
        s = slugify(button_text)
        if s:
            return f"{BUTTON_PREFIX}{s}"
    s = slugify(button_text)
    return f"{BUTTON_PREFIX}_{s}" if s else f"{BUTTON_PREFIX}_"


def _candidate_file_id(label: str) -> str:
    if label:
        s = slugify(label)
        if s:
            return f"{UPLOAD_PREFIX}{s}"
    return f"{UPLOAD_PREFIX}_"


# ── ElementResolver ───────────────────────────────────────────────

class ElementResolver:
    """Bidirectional resolver between semantic IDs and DOM elements.

    **Generation** (used by the Observer):
        Given a Playwright Locator, produce a stable semantic ID
        that can later be resolved back to the same element.

    **Resolution** (used by the Executor):
        Given a semantic ID, find the corresponding DOM element
        via CSS selectors that mirror the generation strategy.

    The resolver maintains a uniqueness tracker so that IDs on the
    same page never collide (e.g. ``field:first_name``,
    ``field:first_name_2``).  Call ``reset()`` between observation
    passes to clear the tracker.
    """

    def __init__(self, page: Page) -> None:
        self._page = page
        self._used_ids: set[str] = set()

    def reset(self) -> None:
        self._used_ids.clear()

    # ── Generation ─────────────────────────────────────────────

    def field_id(self, element: Locator, label: str, field_type: str) -> str:
        candidate = _candidate_field_id(element, label, field_type)
        unique = _make_unique_id(candidate, self._used_ids)
        self._used_ids.add(unique)
        return unique

    def button_id(self, text: str) -> str:
        candidate = _candidate_button_id(text)
        unique = _make_unique_id(candidate, self._used_ids)
        self._used_ids.add(unique)
        return unique

    def file_id(self, label: str) -> str:
        candidate = _candidate_file_id(label)
        unique = _make_unique_id(candidate, self._used_ids)
        self._used_ids.add(unique)
        return unique

    # ── Resolution ─────────────────────────────────────────────
    #
    # Each method returns ``Locator | None``.  If the ID cannot be
    # matched to any element, ``None`` is returned — no fallback
    # to a best-guess element.

    def resolve_field(self, field_id: str) -> Locator | None:
        slug = field_id.split(":", 1)[1] if ":" in field_id else field_id
        label_text = slug.replace("_", " ")

        # 1. aria-label (slug and human-text forms)
        loc = self._try_selector(f'[aria-label="{slug}"]')
        if loc is not None:
            return loc
        loc = self._try_selector(f'[aria-label="{label_text}"]')
        if loc is not None:
            return loc

        # 2. placeholder
        loc = self._try_selector(f'[placeholder="{slug}"]')
        if loc is not None:
            return loc
        loc = self._try_selector(f'[placeholder="{label_text}"]')
        if loc is not None:
            return loc

        # 3. name attribute
        loc = self._try_selector(f'[name="{slug}"]')
        if loc is not None:
            return loc

        # 4. id attribute
        loc = self._try_selector(f"#{slug}")
        if loc is not None:
            return loc

        # 5. Associated <label for="...">
        label_el = self._page.locator(f"label:has-text('{label_text}')").first
        if label_el.count():
            try:
                for_id = label_el.get_attribute("for")
                if for_id:
                    loc = self._page.locator(f"#{for_id}").first
                    if loc.count():
                        return loc
            except Exception:
                pass

        # 6. Partial aria-label / placeholder (case-insensitive)
        loc = self._try_selector(f'[aria-label*="{label_text}" i]')
        if loc is not None:
            return loc
        loc = self._try_selector(f'[placeholder*="{label_text}" i]')
        if loc is not None:
            return loc

        return None

    def resolve_button(self, button_id: str) -> Locator | None:
        slug = button_id.split(":", 1)[1] if ":" in button_id else button_id
        label_text = slug.replace("_", " ")

        # LinkedIn's top-card entry point may be a styled <a> rather than a
        # semantic button. Prefer its site-specific classes before generic
        # text selectors so a job-detail Apply click does not resolve to an
        # unrelated link elsewhere on the page.
        if slug in {"apply", "easy_apply"}:
            for selector in [
                f"button.jobs-apply-button:has-text('{label_text}')",
                f"a.jobs-apply-button:has-text('{label_text}')",
                f"[class*='jobs-apply-button']:has-text('{label_text}')",
            ]:
                loc = self._try_selector(selector)
                if loc is not None:
                    return loc

        for tag_filter in [
            f"button:has-text('{label_text}')",
            f"[role='button']:has-text('{label_text}')",
            f"a:has-text('{label_text}')",
            f"input[type='submit']:has-text('{label_text}')",
            f"input[type='button']:has-text('{label_text}')",
        ]:
            loc = self._try_selector(tag_filter)
            if loc is not None:
                return loc

        return None

    def resolve_file(self, file_id: str) -> Locator | None:
        slug = file_id.split(":", 1)[1] if ":" in file_id else file_id
        label_text = slug.replace("_", " ")

        # 1. aria-label
        loc = self._try_selector(
            f"input[type='file'][aria-label='{slug}']"
        )
        if loc is not None:
            return loc
        loc = self._try_selector(
            f"input[type='file'][aria-label='{label_text}']"
        )
        if loc is not None:
            return loc

        # 2. name / id
        loc = self._try_selector(f"input[type='file'][name='{slug}']")
        if loc is not None:
            return loc
        loc = self._try_selector(f"input[type='file']#{slug}")
        if loc is not None:
            return loc

        # 3. Associated label
        label_el = self._page.locator(f"label:has-text('{label_text}')").first
        if label_el.count():
            try:
                for_id = label_el.get_attribute("for")
                if for_id:
                    loc = self._page.locator(
                        f"input[type='file']#{for_id}"
                    ).first
                    if loc.count():
                        return loc
            except Exception:
                pass

        # 4. Partial aria-label (case-insensitive)
        loc = self._try_selector(
            f"input[type='file'][aria-label*='{label_text}' i]"
        )
        if loc is not None:
            return loc

        return None

    # ── Internal helpers ───────────────────────────────────────

    def _try_selector(self, selector: str) -> Locator | None:
        """Return the first matching locator, or ``None`` if no match."""
        loc = self._page.locator(selector).first
        return loc if loc.count() > 0 else None
