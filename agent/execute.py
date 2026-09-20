from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from playwright.sync_api import Locator, Page

from agent.resolver import ElementResolver


# ── Enum ───────────────────────────────────────────────────────────

class BrowserAction(Enum):
    FILL_FIELD = "fill_field"
    CLICK_BUTTON = "click_button"
    UPLOAD_FILE = "upload_file"
    SELECT_OPTION = "select_option"
    CHECK_CHECKBOX = "check_checkbox"
    SCROLL_TO = "scroll_to"
    WAIT = "wait"
    STOP_FOR_REVIEW = "stop_for_review"


# ── Data models ────────────────────────────────────────────────────

@dataclass
class BrowserCommand:
    action: BrowserAction
    target: str | None = None
    value: str | None = None
    timeout_ms: int = 10000

    def __post_init__(self) -> None:
        if not isinstance(self.action, BrowserAction):
            raise TypeError(
                f"action must be a BrowserAction enum, got {type(self.action)}"
            )


@dataclass
class ExecutionResult:
    success: bool
    action: str
    target: str | None
    message: str
    duration_ms: int
    exception: str | None = None


# ── Supported action set (for validation) ─────────────────────────

_SUPPORTED_ACTIONS: frozenset[str] = frozenset(e.value for e in BrowserAction)


# ── Executor ───────────────────────────────────────────────────────

class Executor:
    """Deterministic browser action executor.

    Resolves semantic element IDs (e.g. ``field:first_name``,
    ``button:continue``, ``upload:resume``) to Playwright locators
    via the shared ``ElementResolver`` and performs the requested
    action.

    The executor is **stateless** across commands — it holds only a
    reference to the Playwright ``Page`` and a resolver.  It never:
    - Plans, reasons, or decides what to do next.
    - Retries, loops, or orchestrates multi-step workflows.
    - References any ATS (LinkedIn, Workday, Greenhouse, etc.).
    """

    def __init__(self, page: Page) -> None:
        self._page = page
        self._resolver = ElementResolver(page)

    @property
    def page(self) -> Page:
        """The active page, which can change after a safe entry-point click."""
        return self._page

    # ── Public API ─────────────────────────────────────────────

    def execute(self, command: BrowserCommand) -> ExecutionResult:
        if not isinstance(command.action, BrowserAction):
            return ExecutionResult(
                success=False,
                action=str(command.action),
                target=command.target,
                message=f"Invalid action type: {type(command.action).__name__}",
                duration_ms=0,
            )

        action_str = command.action.value
        if action_str not in _SUPPORTED_ACTIONS:
            return ExecutionResult(
                success=False,
                action=action_str,
                target=command.target,
                message=f"Unsupported action: {action_str}",
                duration_ms=0,
            )

        start = time.perf_counter()

        try:
            if command.action == BrowserAction.FILL_FIELD:
                result = self._execute_fill(command)
            elif command.action == BrowserAction.CLICK_BUTTON:
                result = self._execute_click(command)
            elif command.action == BrowserAction.UPLOAD_FILE:
                result = self._execute_upload(command)
            elif command.action == BrowserAction.SELECT_OPTION:
                result = self._execute_select(command)
            elif command.action == BrowserAction.CHECK_CHECKBOX:
                result = self._execute_checkbox(command)
            elif command.action == BrowserAction.SCROLL_TO:
                result = self._execute_scroll(command)
            elif command.action == BrowserAction.WAIT:
                result = self._execute_wait(command)
            else:
                result = ExecutionResult(
                    success=False,
                    action=action_str,
                    target=command.target,
                    message=f"Unimplemented action: {action_str}",
                    duration_ms=0,
                )
        except Exception as exc:
            elapsed = int((time.perf_counter() - start) * 1000)
            return ExecutionResult(
                success=False,
                action=action_str,
                target=command.target,
                message=f"Exception during {action_str}: {exc}",
                duration_ms=elapsed,
                exception=f"{type(exc).__name__}: {exc}",
            )

        elapsed = int((time.perf_counter() - start) * 1000)
        return ExecutionResult(
            success=result.success,
            action=action_str,
            target=command.target,
            message=result.message,
            duration_ms=elapsed,
            exception=result.exception,
        )

    # ── Action implementations ─────────────────────────────────

    def _resolve_locator(self, target: str) -> Locator | None:
        """Resolve a semantic ID by trying field → button → file.

        Returns ``None`` when no element matches — never falls back
        to a best-guess element.
        """
        if target.startswith("field:"):
            return self._resolver.resolve_field(target)
        if target.startswith("button:"):
            return self._resolver.resolve_button(target)
        if target.startswith("upload:"):
            return self._resolver.resolve_file(target)
        return None

    def _execute_fill(self, command: BrowserCommand) -> ExecutionResult:
        target_text = command.target or ""
        locator = self._resolver.resolve_field(target_text)

        if locator is None:
            return ExecutionResult(
                success=False,
                action=command.action.value,
                target=command.target,
                message=f"Field not found: {target_text}",
                duration_ms=0,
            )

        locator.clear(timeout=command.timeout_ms)
        locator.fill(command.value or "", timeout=command.timeout_ms)

        return ExecutionResult(
            success=True,
            action=command.action.value,
            target=command.target,
            message=f"Filled '{target_text}' with '{command.value}'",
            duration_ms=0,
        )

    def _execute_click(self, command: BrowserCommand) -> ExecutionResult:
        target_text = command.target or ""
        locator = self._resolver.resolve_button(target_text)

        if locator is None:
            return ExecutionResult(
                success=False,
                action=command.action.value,
                target=command.target,
                message=f"Button not found: {target_text}",
                duration_ms=0,
            )

        pages_before = self._context_pages()
        locator.click(timeout=command.timeout_ms)

        # Company application links commonly open a new tab. Adopt only that
        # page; the agent re-evaluates the ATS capability before doing
        # anything else on it.
        try:
            self._page.wait_for_timeout(400)
        except Exception:
            pass
        new_pages = [page for page in self._context_pages() if page not in pages_before]
        if new_pages:
            self._page = new_pages[-1]
            self._resolver = ElementResolver(self._page)
            try:
                self._page.wait_for_load_state("domcontentloaded", timeout=command.timeout_ms)
            except Exception:
                pass
            return ExecutionResult(
                success=True,
                action=command.action.value,
                target=command.target,
                message=f"Clicked '{target_text}' and switched to the application tab",
                duration_ms=0,
            )

        return ExecutionResult(
            success=True,
            action=command.action.value,
            target=command.target,
            message=f"Clicked '{target_text}'",
            duration_ms=0,
        )

    def _context_pages(self) -> list[Page]:
        """Return context pages without making click handling brittle in tests."""
        try:
            return list(self._page.context.pages)
        except Exception:
            return []

    def _execute_upload(self, command: BrowserCommand) -> ExecutionResult:
        target_text = command.target or ""
        locator = self._resolver.resolve_file(target_text)

        if locator is None:
            return ExecutionResult(
                success=False,
                action=command.action.value,
                target=command.target,
                message=f"File input not found: {target_text}",
                duration_ms=0,
            )

        file_path = command.value or ""
        if not file_path:
            return ExecutionResult(
                success=False,
                action=command.action.value,
                target=command.target,
                message="No file path provided in value",
                duration_ms=0,
            )

        locator.set_input_files(file_path, timeout=command.timeout_ms)

        return ExecutionResult(
            success=True,
            action=command.action.value,
            target=command.target,
            message=f"Uploaded '{file_path}' to '{target_text}'",
            duration_ms=0,
        )

    def _execute_select(self, command: BrowserCommand) -> ExecutionResult:
        target_text = command.target or ""
        locator = self._resolver.resolve_field(target_text)

        if locator is None:
            return ExecutionResult(
                success=False,
                action=command.action.value,
                target=command.target,
                message=f"Select element not found: {target_text}",
                duration_ms=0,
            )

        locator.select_option(command.value or "", timeout=command.timeout_ms)

        return ExecutionResult(
            success=True,
            action=command.action.value,
            target=command.target,
            message=f"Selected '{command.value}' in '{target_text}'",
            duration_ms=0,
        )

    def _execute_checkbox(self, command: BrowserCommand) -> ExecutionResult:
        target_text = command.target or ""
        locator = self._resolver.resolve_field(target_text)

        if locator is None:
            return ExecutionResult(
                success=False,
                action=command.action.value,
                target=command.target,
                message=f"Checkbox not found: {target_text}",
                duration_ms=0,
            )

        is_checked = locator.is_checked(timeout=command.timeout_ms)
        if not is_checked:
            locator.check(timeout=command.timeout_ms)

        return ExecutionResult(
            success=True,
            action=command.action.value,
            target=command.target,
            message=f"Checkbox '{target_text}' "
            f"{'already checked' if is_checked else 'checked'}",
            duration_ms=0,
        )

    def _execute_scroll(self, command: BrowserCommand) -> ExecutionResult:
        target_text = command.target or ""
        locator = self._resolve_locator(target_text)

        if locator is None:
            return ExecutionResult(
                success=False,
                action=command.action.value,
                target=command.target,
                message=f"Element not found for scroll: {target_text}",
                duration_ms=0,
            )

        locator.scroll_into_view_if_needed(timeout=command.timeout_ms)
        return ExecutionResult(
            success=True,
            action=command.action.value,
            target=command.target,
            message=f"Scrolled '{target_text}' into view",
            duration_ms=0,
        )

    def _execute_wait(self, command: BrowserCommand) -> ExecutionResult:
        delay_s = command.timeout_ms / 1000.0
        time.sleep(delay_s)
        return ExecutionResult(
            success=True,
            action=command.action.value,
            target=command.target,
            message=f"Waited {delay_s}s",
            duration_ms=0,
        )
