from __future__ import annotations

import re
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import Page

from agent.dom import interaction_scope
from agent.resolver import ElementResolver
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

_CAPTCHA_PATTERNS: tuple[str, ...] = (
    "captcha",
    "recaptcha",
    "verify you are human",
    "security challenge",
)

_EXTERNAL_APPLY_PATTERNS: tuple[str, ...] = (
    "your profile was shared with the job poster",
    "job moved to in progress under clicked apply",
    "did you finish applying?",
)


def _normalised_notice_text(text: str) -> str:
    """Normalise browser toast text before making a safety decision."""
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _is_linkedin_progress_notice(text: str) -> bool:
    """Return true for LinkedIn's non-error external-apply tracking toast.

    LinkedIn exposes this as a role=alert even though it means that the
    generic Apply action was accepted.  Treating it as form validation blocks
    the handoff before the agent can inspect the external destination.
    """
    notice = _normalised_notice_text(text)
    return any(
        pattern in notice
        for pattern in (
            "job moved to in progress under clicked apply",
            "your profile was shared with the job poster",
            "did you finish applying?",
        )
    )


_FIELD_SELECTORS: dict[str, str] = {
    "input": (
        "input:not([type='hidden']):not([type='file']):not([type='submit'])"
        ":not([type='reset']):not([type='button'])"
    ),
    "textarea": "textarea",
    "select": "select",
    "combobox": "[role='combobox']:not(input):not(select)",
    "radio_group": "[role='radiogroup']",
}

_IGNORED_BUTTON_TEXTS: frozenset[str] = frozenset(
    {
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
    }
)

_IGNORED_BUTTON_REGEX = re.compile(
    r"^\s*\d+\s*(of|/)\s*\d+\s*$"  # "1 of 10", "1/10"
    r"|^\s*\d+\s*$"  # bare page number
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


# ── Navigation-landmark detection ─────────────────────────────────


def _is_inside_nav_landmark(element: Any) -> bool:
    """Check whether *element* (a Playwright Locator) sits inside a
    ``<nav>``, ``<header>``, ``<footer>``, ``[role="navigation"]``,
    ``[role="banner"]``, or ``[role="contentinfo"]``.

    Uses a single ``evaluate`` call per selector to minimise overhead.

    Returns:
        ``True`` if the element is inside any of those landmarks.
    """
    try:
        return (
            element.evaluate(
                """(el, selectors) => Boolean(el.closest(selectors)) &&
                !el.closest('form, dialog, [role=dialog]')""",
                arg=", ".join(_NAV_LANDMARK_SELECTORS),
            )
            is True
        )
    except Exception:
        pass
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


def _classify_page_type(page: Page, legacy_state: str, scope=None) -> str:
    """Classify the page into a generic type using DOM heuristics.

    Classification order (first match wins):

    1. **login_required** — sign-in wall detected by legacy classifier.
    2. **unavailable** — job-not-found text detected by legacy classifier.
    3. **redirect** — detected redirect by legacy classifier.
    4. **confirmation** — body text matches a known submission pattern.
    5. **login_required** (re-check) — body text contains sign-in keywords
       even when legacy classifier missed it.
    6. **unavailable** (re-check) — body text contains job-expired keywords.
    7. **job_details** — known LinkedIn job-view URL with no application
       form.  LinkedIn keeps a global search input in its job-detail header,
       so the URL must win over that navigation-chrome signal.
    8. **search** — page has an input with placeholder matching search
       keywords, but no personal-info form fields.
    9. **application_form** — has 1+ form fields with personal-info labels
       OR file-upload controls.
    10. **application_form** (fallback) — has form fields + buttons with
        application keywords, but no search signals.
    11. **unknown** — none of the above.
    """

    scope = scope if scope is not None else page
    # An open application modal wins over the job URL and its header search.
    # Do not mistake incidental sign-in links outside that modal for a wall.
    if scope is not page:
        try:
            scoped_text = scope.inner_text(timeout=1000).lower()
            if any(needle in scoped_text for needle in _CAPTCHA_PATTERNS):
                return "captcha_detected"
            if scope.locator("input[type='password']:visible").count():
                return "login_required"
            auth_buttons = scope.get_by_role(
                "button", name=re.compile(r"^(sign in|log in|login|create account|sign up)\b", re.I)
            )
            if auth_buttons.count() and auth_buttons.first.is_visible():
                return "login_required"
            is_form_surface = scope.evaluate("el => el.matches('form, dialog, [role=dialog]')")
            if (
                is_form_surface
                and scope.locator(
                    "input:not([type='hidden']), textarea, select, "
                    "[role='combobox'], [role='radiogroup']"
                ).count()
            ):
                return "application_form"
            if is_form_surface and re.search(
                r"\b(next|continue|review|apply|submit|application)\b", scoped_text
            ):
                return "application_form"
        except Exception:
            pass

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

    normalised_body_text = _normalised_notice_text(body_text)

    if any(needle in normalised_body_text for needle in _CONFIRMATION_PATTERNS):
        return "confirmation"

    if any(needle in normalised_body_text for needle in _CAPTCHA_PATTERNS):
        return "captcha_detected"

    if any(needle in normalised_body_text for needle in _EXTERNAL_APPLY_PATTERNS):
        return "external_apply_started"

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
            elements = scope.locator(selector)
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
            if any(kw in label_lower for kw in ["search", "keyword", "title", "skill", "company"]):
                _has_search_input = True

            # Personal-info indicator
            if any(
                kw in label_lower for kw in ["first name", "last name", "email", "phone", "resume"]
            ):
                _has_personal_form = True

    # ── Classification rules ─────────────────────────────────
    is_linkedin_job_detail = (
        "linkedin.com/jobs/view/" in url_lower and not _has_personal_form and not _has_file_upload
    )
    if is_linkedin_job_detail:
        return "job_details"

    if _has_search_input and not _has_personal_form and not _has_file_upload:
        return "search"

    if _has_job_description and _field_count <= 1 and not _has_file_upload:
        return "job_details"

    if _field_count > 0 or _has_file_upload:
        return "application_form"

    return "unknown"


# ── Field extraction ──────────────────────────────────────────────


def _extract_fields(page: Page, resolver: ElementResolver) -> list[FormField]:
    fields: list[FormField] = []
    radio_groups: set[str] = set()

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
            options = []
            invalid = False
            group_required = False

            try:
                if selector_key == "input":
                    element_type = element.get_attribute("type") or "text"
                    if element.get_attribute("role") == "combobox":
                        element_type = "combobox"
                    try:
                        if element_type in ("checkbox", "radio"):
                            current_value = "true" if element.is_checked(timeout=300) else ""
                        else:
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
                    current_value = element.input_value(timeout=300)
                    options = element.locator("option").evaluate_all(
                        "els => els.filter(x => !x.disabled).map(x => "
                        "({value:x.value, label:x.textContent.trim()}))"
                    )
                    selected_label = (
                        element.locator("option:checked").inner_text(timeout=300).strip()
                    )
                    if re.match(r"^(select|choose)\b", selected_label, re.I):
                        current_value = ""
                elif selector_key == "combobox":
                    element_type = "combobox"
                    current_value = (
                        element.get_attribute("data-value")
                        or element.inner_text(timeout=300).strip()
                    )
                    if element.get_attribute("aria-placeholder") == current_value:
                        current_value = ""
                    if re.match(r"^(select|choose)\b", current_value, re.I):
                        current_value = ""
                elif selector_key == "radio_group":
                    element_type = "radio_group"
                    checked = element.locator("[role='radio'][aria-checked='true']")
                    current_value = ""
                    if checked.count():
                        current_value = (
                            checked.first.get_attribute("data-value")
                            or checked.first.get_attribute("aria-label")
                            or checked.first.inner_text(timeout=300)
                        )
                    options = element.locator("[role='radio']").evaluate_all(
                        """els => els.filter(x => x.getAttribute('aria-disabled') !== 'true')
                        .map(x => ({value:x.getAttribute('data-value') || x.textContent.trim(),
                            label:x.getAttribute('aria-label') || x.textContent.trim()}))"""
                    )
            except Exception:
                continue

            if element_type in ("hidden", "submit", "reset", "button"):
                continue

            label = label_text_for_input(element)

            if element_type == "radio":
                if element.evaluate("el => Boolean(el.closest('[role=radiogroup]'))"):
                    continue
                name = element.get_attribute("name") or ""
                if name:
                    # Treat a native radio question as one field, not multiple
                    # independently required booleans.
                    group = element.evaluate("el => (el.form ? el.form.id : '') + ':' + el.name")
                    if group in radio_groups:
                        continue
                    radio_groups.add(group)
                    data = element.evaluate("""el => {
                        const root = el.form || el.closest('[role=dialog], dialog, main') ||
                            el.getRootNode();
                        const radios = Array.from(root.querySelectorAll('input[type=radio]'))
                            .filter(x => x.name === el.name);
                        const fieldset = el.closest('fieldset');
                        return {value: (radios.find(x => x.checked) || {}).value || '',
                            label: fieldset?.querySelector('legend')?.textContent.trim() || '',
                            required: radios.some(x => x.required ||
                                x.getAttribute('aria-required') === 'true'),
                            options: radios.filter(x => !x.disabled).map(x => ({value:x.value,
                                label:Array.from(x.labels || []).map(l => l.textContent.trim())
                                    .join(' ') || x.getAttribute('aria-label') || x.value}))};
                    }""")
                    current_value = data["value"]
                    group_required = data["required"]
                    options = data["options"]
                    label = data["label"] or label
                    element_type = "radio_group"

            required = False
            try:
                required = (
                    element.get_attribute("required") is not None
                    or element.get_attribute("aria-required") == "true"
                    or group_required
                )
                invalid = element.get_attribute("aria-invalid") == "true" or (
                    bool(current_value)
                    and element.evaluate("el => Boolean(el.validity && !el.validity.valid)") is True
                )
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
                readonly = readonly_attr is not None and element_type != "combobox"
            except Exception:
                pass

            field_id = resolver.field_id(element, label, element_type)

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
                    options=options,
                    invalid=invalid,
                )
            )

    return fields


# ── Button extraction ─────────────────────────────────────────────


def _extract_buttons(page: Page, resolver: ElementResolver) -> list[Button]:
    buttons: list[Button] = []

    button_selectors = [
        "button",
        "a[role='button']",
        # Several LinkedIn job cards implement their Apply entry point as a
        # styled anchor without role="button".
        "a[href]",
        "[role='button']:not(a)",
        "input[type='submit'], input[type='button']",
    ]

    # A CSS union returns each DOM node once while retaining distinct buttons
    # with identical names (for example, disabled and enabled Next controls).
    for selector in [", ".join(button_selectors)]:
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
                text = (
                    element.inner_text(timeout=300).strip()
                    or element.get_attribute("aria-label")
                    or element.get_attribute("value")
                    or ""
                )
                if not text:
                    continue
            except Exception:
                continue

            # Filter out navigation / accessibility / UI chrome
            if _is_ignored_button(text):
                continue

            # Filter out buttons inside nav / header / footer landmarks
            if _is_inside_nav_landmark(element):
                continue

            button_type = "button"
            href = ""
            try:
                btn_type = element.get_attribute("type")
                if btn_type == "submit":
                    button_type = "submit"
            except Exception:
                pass
            try:
                href = element.get_attribute("href") or ""
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

            button_id = resolver.button_id(text)
            resolver.remember(button_id, element)

            interactable = visible and enabled

            buttons.append(
                Button(
                    id=button_id,
                    text=text,
                    button_type=button_type,
                    visible=visible,
                    enabled=enabled,
                    interactable=interactable,
                    href=href,
                )
            )

    return buttons


# ── File-input extraction ─────────────────────────────────────────


def _extract_file_inputs(page: Page, resolver: ElementResolver) -> list[FileInput]:
    inputs: list[FileInput] = []

    try:
        elements = page.locator("input[type='file']")
        count = min(elements.count(), 20)
    except Exception:
        return inputs

    for index in range(count):
        element = elements.nth(index)

        try:
            if (
                element.evaluate(
                    "el => Boolean(el.closest('[hidden], [aria-hidden=true]')) || "
                    "!el.parentElement.getClientRects().length"
                )
                is True
            ):
                continue
        except Exception:
            continue

        label = label_text_for_input(element)

        has_file = False
        required = False
        try:
            has_file = element.input_value(timeout=300) != ""
        except Exception:
            pass
        try:
            required = element.get_attribute("required") is not None
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

        file_id = resolver.file_id(label)
        resolver.remember(file_id, element)

        # File controls are commonly hidden behind an upload button. Playwright
        # can set their files directly even when the input itself is invisible.
        interactable = enabled

        inputs.append(
            FileInput(
                id=file_id,
                label=label or f"File Upload {index + 1}",
                has_file=has_file,
                required=required,
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
                        text_lower = _normalised_notice_text(text)
                        # LinkedIn uses role=alert for informational toasts,
                        # including its "profile was shared" click-tracker.
                        # Only preserve messages with a real validation/error
                        # signal for the verifier.
                        if _is_linkedin_progress_notice(text):
                            continue
                        if text and any(
                            marker in text_lower
                            for marker in (
                                "error",
                                "invalid",
                                "required",
                                "please correct",
                                "please enter",
                                "please fix",
                                "unable",
                                "failed",
                            )
                        ):
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

    scope = interaction_scope(page)
    page_type = _classify_page_type(page, legacy_state, scope)

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

    resolver = ElementResolver(page)
    resolver.reset()

    fields = _extract_fields(scope, resolver)
    buttons = _extract_buttons(scope, resolver)
    file_inputs = _extract_file_inputs(scope, resolver)
    error_messages = _detect_error_messages(scope)
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
