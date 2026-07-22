from __future__ import annotations

import hashlib
import re
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import Page

from agent.types import Button, FileInput, FormField, PageSnapshot
from browser.extraction import (
    classify_page_state,
    label_text_for_input,
)


# ── Constants ──────────────────────────────────────────────────────

_CONFIRMATION_PATTERNS: list[str] = [
    "your application has been submitted",
    "thank you for applying",
    "application submitted",
    "we received your application",
    "your submission has been received",
]

_ERROR_PATTERNS: list[str] = [
    "please correct",
    "this field is required",
    "is required",
    "please enter a valid",
    "invalid format",
    "please fix",
]

_FIELD_SELECTORS: dict[str, str] = {
    "input": "input:not([type='hidden']):not([type='submit']):not([type='reset']):not([type='button'])",
    "textarea": "textarea",
    "select": "select",
}

_IGNORED_BUTTON_TEXTS: frozenset[str] = frozenset({
    # Accessibility / navigation chrome
    "skip to main content",
    "skip to search",
    "skip to content",
    "keyboard shortcuts",
    "accessibility",
    # Global navigation
    "messaging",
    "notifications",
    "notifications",
    "profile",
    "network",
    "jobs",
    "home",
    "my items",
    # Social / sharing
    "share",
    "share profile",
    "follow",
    "like",
    "comment",
    "send",
    "report",
    # Pagination
    "previous",
    "next",
    "page",
    "pagination",
    # Filter / sort
    "sort by",
    "sort",
    "filter",
    "clear all",
    "show results",
    # Search results chrome
    "search",
    "search this page",
    "advanced search",
    "save search",
    # View controls
    "grid view",
    "list view",
    "map view",
    "view details",
    "expand all",
    "collapse all",
})

_IGNORED_BUTTON_REGEX = re.compile(
    r"^\s*\d+\s*(of|/)\s*\d+\s*$"  # "1 of 10", "1/10"
    r"|^\s*\d+\s*$"                  # bare page number
    r"|^items per page",
    re.IGNORECASE,
)

# Landmarks inside which buttons are typically navigation chrome
_NAV_LANDMARK_SELECTORS = [
    "nav",
    "header",
    "footer",
    "[role='navigation']",
    "[role='banner']",
    "[role='contentinfo']",
]


# ── ID helpers ─────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def _element_fingerprint(element: Any, field_type: str) -> str:
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


def _make_candidate_field_id(element: Any, label: str, field_type: str) -> str:
    if label:
        slug = _slugify(label)
        if slug:
            return f"field:{slug}"
    try:
        name = element.get_attribute("name")
        if name and name.strip():
            safe_name = _slugify(name.strip())
            if safe_name:
                return f"field:{safe_name}"
    except Exception:
        pass
    try:
        elem_id = element.get_attribute("id")
        if elem_id and elem_id.strip():
            safe_id = _slugify(elem_id.strip())
            if safe_id:
                return f"field:{safe_id}"
    except Exception:
        pass
    fingerprint = _element_fingerprint(element, field_type)
    return f"field:{fingerprint}"


def _make_candidate_button_id(button_text: str) -> str:
    if button_text:
        slug = _slugify(button_text)
        if slug:
            return f"button:{slug}"
    return f"button:_{_slugify(button_text)}" if button_text else "button:_"


def _make_candidate_file_id(label: str) -> str:
    if label:
        slug = _slugify(label)
        if slug:
            return f"upload:{slug}"
    return "upload:_"


def _make_unique_id(candidate_id: str, used_ids: set[str]) -> str:
    """Ensure uniqueness by appending ``_2``, ``_3``, etc.

    Args:
        candidate_id: The semantic ID produced by the make-candidate function.
        used_ids: Set of IDs already assigned in the current extraction pass.

    Returns:
        The candidate ID if unused, or ``candidate_id + _N`` for the
        first available suffix.
    """
    if candidate_id not in used_ids:
        return candidate_id
    suffix = 2
    while f"{candidate_id}_{suffix}" in used_ids:
        suffix += 1
    return f"{candidate_id}_{suffix}"


# ── Navigation-landmark detection ─────────────────────────────────

def _is_inside_nav_landmark(element: Any) -> bool:
    """Check whether *element* (a Playwright Locator) sits inside a
    ``<nav>``, ``<header>``, ``<footer>``, ``[role="navigation"]``,
    ``[role="banner"]``, or ``[role="contentinfo"]``.

    Uses a single ``evaluate`` call per selector to minimise overhead.

    Returns:
        ``True`` if the element is inside any of those landmarks.
    """
    for selector in _NAV_LANDMARK_SELECTORS:
        try:
            inside = element.page.evaluate(
                """(element, sel) => {
                    let el = element;
                    while (el && el !== document.body) {
                        if (el.matches(sel)) return true;
                        el = el.parentElement;
                    }
                    return false;
                }""",
                arg=[element.element_handle(), selector],
            )
            if inside:
                return True
        except Exception:
            continue
    return False


# ── Button filtering ──────────────────────────────────────────────

def _is_ignored_button(text: str) -> bool:
    text_lower = text.strip().lower()
    if not text_lower or len(text_lower) <= 2:
        return True
    if text_lower in _IGNORED_BUTTON_TEXTS:
        return True
    if _IGNORED_BUTTON_REGEX.search(text_lower):
        return True
    return False


# ── Page type classification ──────────────────────────────────────

def _classify_page_type(page: Page, legacy_state: str) -> str:
    """Classify the page into a generic type using DOM heuristics.

    Classification order (first match wins):

    1. **login_required** — sign-in wall detected by legacy classifier.
    2. **unavailable** — job-not-found text detected by legacy classifier.
    3. **redirect** — detected redirect by legacy classifier.
    4. **confirmation** — body text matches a known submission pattern.
    5. **login_required** (re-check) — body text contains sign-in keywords
       even when legacy classifier missed it.
    6. **unavailable** (re-check) — body text contains job-expired keywords.
    7. **search** — page has an input with placeholder matching search
       keywords, but no personal-info form fields.
    8. **job_details** — page has structured job-description content and
       at most one form field or button.
    9. **application_form** — has 1+ form fields with personal-info labels
       OR file-upload controls.
    10. **application_form** (fallback) — has form fields + buttons with
        application keywords, but no search signals.
    11. **unknown** — none of the above.
    """

    # ── Fast path: legacy classifier results ─────────────────
    if legacy_state == "account_required":
        return "login_required"
    if legacy_state == "job_unavailable":
        return "unavailable"
    if legacy_state == "job_apply_redirect_lost":
        return "redirect"

    # ── Body text ────────────────────────────────────────────
    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=1000).lower()
    except Exception:
        pass

    if any(needle in body_text for needle in _CONFIRMATION_PATTERNS):
        return "confirmation"

    if any(needle in body_text for needle in _ERROR_PATTERNS):
        if any(needle in body_text for needle in _CONFIRMATION_PATTERNS):
            return "confirmation"

    # Re-check with body text for missed classifications
    _LOGIN_SIGNALS = ["sign in", "log in", "login", "create account"]
    _UNAVAILABLE_SIGNALS = [
        "job no longer available",
        "position has been filled",
        "this job is no longer accepting applications",
        "job has been removed",
    ]

    if any(needle in body_text for needle in _LOGIN_SIGNALS):
        return "login_required"
    if any(needle in body_text for needle in _UNAVAILABLE_SIGNALS):
        return "unavailable"

    # ── DOM heuristics ───────────────────────────────────────
    url_lower = ""
    try:
        url_lower = page.url.lower()
    except Exception:
        pass

    # Detect search pages
    _has_search_input = False
    _has_personal_form = False
    _has_file_upload = False
    _field_count = 0
    _has_job_description = False

    try:
        upload_count = page.locator("input[type='file']").count()
        _has_file_upload = upload_count > 0
    except Exception:
        pass

    try:
        jd_selectors = [
            ".job-description",
            "[aria-label*='job description' i]",
            "[aria-label*='job details' i]",
            "[data-job-id]",
            ".show-more-less-html",
            "article[class*='job']",
            "section[class*='job-description']",
        ]
        for sel in jd_selectors:
            if page.locator(sel).first.count() > 0:
                _has_job_description = True
                break
    except Exception:
        pass

    # Inspect visible input fields
    for selector in _FIELD_SELECTORS.values():
        try:
            elements = page.locator(selector)
            count = min(elements.count(), 50)
        except Exception:
            continue
        for idx in range(count):
            el = elements.nth(idx)
            try:
                if not el.is_visible(timeout=300):
                    continue
            except Exception:
                continue
            try:
                el_type = el.get_attribute("type") or "text"
            except Exception:
                el_type = "text"
            if el_type in ("hidden", "submit", "reset", "button"):
                continue

            _field_count += 1
            label = label_text_for_input(el)
            label_lower = label.lower()

            # Search indicator
            if any(
                kw in label_lower
                for kw in ["search", "keyword", "title", "skill", "company"]
            ):
                _has_search_input = True

            # Personal-info indicator
            if any(
                kw in label_lower
                for kw in ["first name", "last name", "email", "phone", "resume"]
            ):
                _has_personal_form = True

    # ── Classification rules ─────────────────────────────────
    if _has_search_input and not _has_personal_form and not _has_file_upload:
        return "search"

    if _has_job_description and _field_count <= 1 and not _has_file_upload:
        return "job_details"

    if _field_count > 0 or _has_file_upload:
        return "application_form"

    return "unknown"


# ── Field extraction ──────────────────────────────────────────────

def _extract_fields(page: Page) -> list[FormField]:
    fields: list[FormField] = []
    used_ids: set[str] = set()

    for selector_key, selector in _FIELD_SELECTORS.items():
        try:
            elements = page.locator(selector)
            count = min(elements.count(), 200)
        except Exception:
            continue

        for index in range(count):
            element = elements.nth(index)

            try:
                if not element.is_visible(timeout=300):
                    continue
            except Exception:
                continue

            element_type = "text"
            current_value = ""

            try:
                if selector_key == "input":
                    element_type = element.get_attribute("type") or "text"
                    try:
                        current_value = element.input_value(timeout=300)
                    except Exception:
                        current_value = ""
                elif selector_key == "textarea":
                    element_type = "textarea"
                    try:
                        current_value = element.input_value(timeout=300)
                    except Exception:
                        current_value = ""
                elif selector_key == "select":
                    element_type = "select"
            except Exception:
                continue

            if element_type in ("hidden", "submit", "reset", "button"):
                continue

            label = label_text_for_input(element)

            required = False
            try:
                required = element.get_attribute("required") is not None
            except Exception:
                pass

            visible = True
            enabled = True
            readonly = False
            try:
                visible = element.is_visible(timeout=300)
            except Exception:
                pass
            try:
                enabled = element.is_enabled(timeout=300)
            except Exception:
                pass
            try:
                readonly_attr = element.get_attribute("readonly")
                readonly = readonly_attr is not None
            except Exception:
                pass

            candidate = _make_candidate_field_id(element, label, element_type)
            field_id = _make_unique_id(candidate, used_ids)
            used_ids.add(field_id)

            interactable = visible and enabled and not readonly

            fields.append(
                FormField(
                    id=field_id,
                    field_type=element_type,
                    label=label or f"Field {len(fields) + 1}",
                    value=current_value,
                    required=required,
                    visible=visible,
                    enabled=enabled,
                    readonly=readonly,
                    interactable=interactable,
                )
            )

    return fields


# ── Button extraction ─────────────────────────────────────────────

def _extract_buttons(page: Page) -> list[Button]:
    buttons: list[Button] = []
    used_ids: set[str] = set()
    seen_texts: set[str] = set()

    button_selectors = [
        "button",
        "a[role='button']",
        "[role='button']:not(a)",
    ]

    for selector in button_selectors:
        try:
            elements = page.locator(selector)
            count = min(elements.count(), 200)
        except Exception:
            continue

        for index in range(count):
            element = elements.nth(index)

            try:
                if not element.is_visible(timeout=300):
                    continue
            except Exception:
                continue

            try:
                text = element.inner_text(timeout=300).strip()
                if not text or text in seen_texts:
                    continue
            except Exception:
                continue

            # Filter out navigation / accessibility / UI chrome
            if _is_ignored_button(text):
                continue

            # Filter out buttons inside nav / header / footer landmarks
            if _is_inside_nav_landmark(element):
                continue

            seen_texts.add(text)

            button_type = "button"
            try:
                btn_type = element.get_attribute("type")
                if btn_type == "submit":
                    button_type = "submit"
            except Exception:
                pass

            visible = True
            enabled = True
            try:
                visible = element.is_visible(timeout=300)
            except Exception:
                pass
            try:
                enabled = element.is_enabled(timeout=300)
            except Exception:
                pass

            candidate = _make_candidate_button_id(text)
            button_id = _make_unique_id(candidate, used_ids)
            used_ids.add(button_id)

            interactable = visible and enabled

            buttons.append(
                Button(
                    id=button_id,
                    text=text,
                    button_type=button_type,
                    visible=visible,
                    enabled=enabled,
                    interactable=interactable,
                )
            )

    return buttons


# ── File-input extraction ─────────────────────────────────────────

def _extract_file_inputs(page: Page) -> list[FileInput]:
    inputs: list[FileInput] = []
    used_ids: set[str] = set()

    try:
        elements = page.locator("input[type='file']")
        count = min(elements.count(), 20)
    except Exception:
        return inputs

    for index in range(count):
        element = elements.nth(index)

        try:
            if not element.is_visible(timeout=300):
                continue
        except Exception:
            continue

        label = label_text_for_input(element)

        has_file = False
        try:
            has_file = element.input_value(timeout=300) != ""
        except Exception:
            pass

        visible = True
        enabled = True
        try:
            visible = element.is_visible(timeout=300)
        except Exception:
            pass
        try:
            enabled = element.is_enabled(timeout=300)
        except Exception:
            pass

        candidate = _make_candidate_file_id(label)
        file_id = _make_unique_id(candidate, used_ids)
        used_ids.add(file_id)

        interactable = visible and enabled

        inputs.append(
            FileInput(
                id=file_id,
                label=label or f"File Upload {index + 1}",
                has_file=has_file,
                visible=visible,
                enabled=enabled,
                interactable=interactable,
            )
        )

    return inputs


# ── Error / status detection ──────────────────────────────────────

def _detect_error_messages(page: Page) -> list[str]:
    messages: list[str] = []

    error_selectors = [
        "[role='alert']",
        "[aria-live='assertive']",
        ".error-message",
        ".field-error",
        ".validation-error",
        ".form-error",
    ]

    for selector in error_selectors:
        try:
            elements = page.locator(selector)
            for index in range(min(elements.count(), 20)):
                element = elements.nth(index)
                try:
                    if element.is_visible(timeout=300):
                        text = element.inner_text(timeout=300).strip()
                        if text:
                            messages.append(text)
                except Exception:
                    continue
        except Exception:
            continue

    return messages


def _detect_status_message(page: Page) -> str:
    try:
        body_text = page.locator("body").inner_text(timeout=1000).lower()
    except Exception:
        return ""

    for pattern in _CONFIRMATION_PATTERNS:
        if pattern in body_text:
            return pattern

    return ""


# ── Main entry point ──────────────────────────────────────────────

def observe_page(page: Page) -> PageSnapshot:
    """Build a structured snapshot of the current page state.

    This is the primary entry point for the perception layer.
    It extracts form fields, buttons, file inputs, error messages,
    and status text — all **without modifying the page**.

    The snapshot is designed to be:
    - **Read-only** — never clicks, fills, navigates, or uploads.
    - **ATS-agnostic** — uses generic DOM queries, not ATS-specific
      selectors.
    - **Token-efficient** — structured dict, not raw HTML.
    - **Stable** — element IDs are derived from labels and attributes,
      not sequential counters.

    Args:
        page: An active Playwright page object.

    Returns:
        A PageSnapshot with the current page state. Returns a minimal
        snapshot if the page is not accessible.
    """

    url = ""
    page_title = ""
    domain = ""

    try:
        url = page.url
    except Exception:
        pass

    try:
        page_title = page.title()
    except Exception:
        pass

    try:
        domain = urllib.parse.urlparse(url).netloc
    except Exception:
        pass

    legacy_state = "unknown"
    try:
        legacy_state = classify_page_state(page)
    except Exception:
        pass

    page_type = _classify_page_type(page, legacy_state)

    # Short-circuit: login/unavailable/redirect pages rarely have
    # useful form fields — skip heavy extraction.
    if page_type in ("login_required", "unavailable", "redirect"):
        now = datetime.now(timezone.utc)
        return PageSnapshot(
            url=url,
            page_title=page_title,
            domain=domain,
            page_type=page_type,
            observation_timestamp=now.isoformat(timespec="seconds"),
            observation_id=uuid.uuid4().hex[:12],
        )

    fields = _extract_fields(page)
    buttons = _extract_buttons(page)
    file_inputs = _extract_file_inputs(page)
    error_messages = _detect_error_messages(page)
    status_message = _detect_status_message(page)

    now = datetime.now(timezone.utc)

    return PageSnapshot(
        url=url,
        page_title=page_title,
        domain=domain,
        page_type=page_type,
        fields=fields,
        buttons=buttons,
        file_inputs=file_inputs,
        error_messages=error_messages,
        status_message=status_message,
        observation_timestamp=now.isoformat(timespec="seconds"),
        observation_id=uuid.uuid4().hex[:12],
    )
