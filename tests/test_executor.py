"""Unit tests for the Executor.

Uses mocked Playwright objects — no browser launch required.

Run:
    python -m pytest tests/test_executor.py -v
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from agent.execute import (
    BrowserAction,
    BrowserCommand,
    ExecutionResult,
    Executor,
)
from agent.resolver import ElementResolver


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def mock_page():
    """Return a MagicMock that looks like a Playwright Page."""
    page = MagicMock()
    # Make locator().count() default to 0
    default_locator = MagicMock()
    default_locator.count.return_value = 0
    default_locator.first = default_locator
    page.locator.return_value = default_locator
    return page


@pytest.fixture
def executor(mock_page):
    """Return an Executor wired to a mock page."""
    return Executor(mock_page)


def _make_locator(count: int = 1, **attrs) -> MagicMock:
    """Build a locator mock that returns the given count and attributes.

    Supports chaining:
        locator.first → locator
        locator.nth(i) → locator
    """
    locator = MagicMock()
    locator.count.return_value = count
    for key, val in attrs.items():
        setattr(locator, key, val)
    # Chain .first and .nth back to self
    locator.first = locator
    locator.nth.return_value = locator
    return locator


# ── BrowserCommand / BrowserAction tests ──────────────────────────

class TestBrowserCommand:
    def test_enum_values(self):
        assert BrowserAction.FILL_FIELD.value == "fill_field"
        assert BrowserAction.CLICK_BUTTON.value == "click_button"
        assert BrowserAction.UPLOAD_FILE.value == "upload_file"
        assert BrowserAction.SELECT_OPTION.value == "select_option"
        assert BrowserAction.CHECK_CHECKBOX.value == "check_checkbox"
        assert BrowserAction.SCROLL_TO.value == "scroll_to"
        assert BrowserAction.WAIT.value == "wait"

    def test_command_creation(self):
        cmd = BrowserCommand(
            action=BrowserAction.FILL_FIELD,
            target="field:first_name",
            value="John",
            timeout_ms=5000,
        )
        assert cmd.action == BrowserAction.FILL_FIELD
        assert cmd.target == "field:first_name"
        assert cmd.value == "John"
        assert cmd.timeout_ms == 5000

    def test_command_default_timeout(self):
        cmd = BrowserCommand(action=BrowserAction.WAIT)
        assert cmd.timeout_ms == 10000

    def test_command_rejects_non_enum(self):
        with pytest.raises(TypeError):
            BrowserCommand(action="fill_field")  # type: ignore[arg-type]


# ── ExecutionResult tests ─────────────────────────────────────────

class TestExecutionResult:
    def test_result_creation(self):
        result = ExecutionResult(
            success=True,
            action="fill_field",
            target="field:name",
            message="OK",
            duration_ms=150,
        )
        assert result.success is True
        assert result.exception is None

    def test_result_with_exception(self):
        result = ExecutionResult(
            success=False,
            action="click_button",
            target="button:submit",
            message="Error",
            duration_ms=50,
            exception="TimeoutError: element not visible",
        )
        assert result.exception == "TimeoutError: element not visible"


# ── Executor: error handling ──────────────────────────────────────

class TestExecutorErrorHandling:
    def test_invalid_action_type(self, executor):
        """Passing a non-enum action string should fail gracefully."""
        cmd = BrowserCommand(action=BrowserAction.FILL_FIELD)
        # Mutate the action to simulate bad input (can't happen via normal API)
        with patch.object(cmd, "action", "bogus_action"):
            result = executor.execute(cmd)  # type: ignore[arg-type]
        assert result.success is False
        assert "Invalid" in result.message or "Unsupported" in result.message

    def test_field_not_found(self, executor, mock_page):
        """FILL_FIELD on a missing element returns failure."""
        mock_page.locator.return_value.count.return_value = 0

        cmd = BrowserCommand(
            action=BrowserAction.FILL_FIELD,
            target="field:nonexistent",
            value="hello",
        )
        result = executor.execute(cmd)
        assert result.success is False
        assert "not found" in result.message.lower()

    def test_button_not_found(self, executor, mock_page):
        mock_page.locator.return_value.count.return_value = 0

        cmd = BrowserCommand(
            action=BrowserAction.CLICK_BUTTON,
            target="button:missing",
        )
        result = executor.execute(cmd)
        assert result.success is False
        assert "not found" in result.message.lower()

    def test_upload_no_file_path(self, executor, mock_page):
        """UPLOAD_FILE with empty value fails."""
        locator = _make_locator(count=1)
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.UPLOAD_FILE,
            target="upload:resume",
            value="",
        )
        result = executor.execute(cmd)
        assert result.success is False
        assert "No file path" in result.message

    def test_exception_during_execution(self, executor, mock_page):
        """An unhandled exception returns a failure result with exception text."""
        locator = _make_locator(count=1)
        locator.fill.side_effect = RuntimeError("Browser crashed")
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.FILL_FIELD,
            target="field:name",
            value="John",
        )
        result = executor.execute(cmd)
        assert result.success is False
        assert result.exception is not None
        assert "RuntimeError" in result.exception

    def test_duration_ms_set_on_success(self, executor, mock_page):
        locator = _make_locator(count=1)
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.WAIT,
            timeout_ms=1,
        )
        result = executor.execute(cmd)
        assert result.success is True
        assert result.duration_ms >= 0

    def test_duration_ms_set_on_failure(self, executor, mock_page):
        mock_page.locator.return_value.count.return_value = 0

        cmd = BrowserCommand(
            action=BrowserAction.CLICK_BUTTON,
            target="button:none",
        )
        result = executor.execute(cmd)
        assert result.success is False
        assert result.duration_ms >= 0


# ── Executor: action execution ────────────────────────────────────

def test_click_switches_to_a_new_application_tab(mock_page):
    popup_page = MagicMock()
    context_pages = [mock_page]
    mock_page.context.pages = context_pages
    locator = _make_locator(count=1)
    locator.click.side_effect = lambda **_: context_pages.append(popup_page)
    mock_page.locator.return_value = locator
    executor = Executor(mock_page)

    result = executor.execute(
        BrowserCommand(action=BrowserAction.CLICK_BUTTON, target="button:apply")
    )

    assert result.success is True
    assert "switched to the application tab" in result.message
    assert executor.page is popup_page

class TestExecutorFillField:
    def test_fill_success(self, executor, mock_page):
        locator = _make_locator(count=1)
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.FILL_FIELD,
            target="field:first_name",
            value="John",
        )
        result = executor.execute(cmd)

        assert result.success is True
        assert result.action == "fill_field"
        assert "Filled" in result.message
        locator.clear.assert_called_once()
        locator.fill.assert_called_once_with("John", timeout=10000)

    def test_fill_custom_timeout(self, executor, mock_page):
        locator = _make_locator(count=1)
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.FILL_FIELD,
            target="field:email",
            value="a@b.com",
            timeout_ms=3000,
        )
        executor.execute(cmd)

        locator.fill.assert_called_once_with("a@b.com", timeout=3000)


class TestExecutorClickButton:
    def test_click_success(self, executor, mock_page):
        locator = _make_locator(count=1)
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.CLICK_BUTTON,
            target="button:continue",
        )
        result = executor.execute(cmd)

        assert result.success is True
        assert result.action == "click_button"
        assert "Clicked" in result.message
        locator.click.assert_called_once_with(timeout=10000)


class TestExecutorUploadFile:
    def test_upload_success(self, executor, mock_page):
        locator = _make_locator(count=1)
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.UPLOAD_FILE,
            target="upload:resume",
            value="/path/to/resume.pdf",
        )
        result = executor.execute(cmd)

        assert result.success is True
        assert result.action == "upload_file"
        assert "Uploaded" in result.message
        locator.set_input_files.assert_called_once_with(
            "/path/to/resume.pdf", timeout=10000
        )


class TestExecutorSelectOption:
    def test_select_success(self, executor, mock_page):
        locator = _make_locator(count=1)
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.SELECT_OPTION,
            target="field:country",
            value="India",
        )
        result = executor.execute(cmd)

        assert result.success is True
        assert result.action == "select_option"
        assert "Selected" in result.message
        locator.select_option.assert_called_once_with("India", timeout=10000)


class TestExecutorCheckCheckbox:
    def test_check_unchecked(self, executor, mock_page):
        locator = _make_locator(count=1)
        locator.is_checked.return_value = False
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.CHECK_CHECKBOX,
            target="field:agree_terms",
        )
        result = executor.execute(cmd)

        assert result.success is True
        assert "checked" in result.message.lower()
        locator.check.assert_called_once_with(timeout=10000)

    def test_check_already_checked(self, executor, mock_page):
        locator = _make_locator(count=1)
        locator.is_checked.return_value = True
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.CHECK_CHECKBOX,
            target="field:already_checked",
        )
        result = executor.execute(cmd)

        assert result.success is True
        assert "already checked" in result.message.lower()
        locator.check.assert_not_called()


class TestExecutorScrollTo:
    def test_scroll_field_success(self, executor, mock_page):
        """Scroll a field ID via resolver."""
        mock_page.locator.return_value = _make_locator(count=1)

        cmd = BrowserCommand(
            action=BrowserAction.SCROLL_TO,
            target="field:first_name",
        )
        result = executor.execute(cmd)

        assert result.success is True
        assert "Scrolled" in result.message

    def test_scroll_button_success(self, executor, mock_page):
        """Scroll a button ID via resolver."""
        mock_page.locator.return_value = _make_locator(count=1)

        cmd = BrowserCommand(
            action=BrowserAction.SCROLL_TO,
            target="button:continue",
        )
        result = executor.execute(cmd)

        assert result.success is True
        assert "Scrolled" in result.message

    def test_scroll_element_not_found(self, executor, mock_page):
        """When resolver returns None for unrecognized prefix."""
        mock_page.locator.return_value = _make_locator(count=0)

        cmd = BrowserCommand(
            action=BrowserAction.SCROLL_TO,
            target="unknown:id",
        )
        result = executor.execute(cmd)

        assert result.success is False
        assert "not found" in result.message.lower()


class TestExecutorWait:
    def test_wait_success(self, executor, mock_page):
        cmd = BrowserCommand(
            action=BrowserAction.WAIT,
            timeout_ms=10,
        )
        t0 = time.perf_counter()
        result = executor.execute(cmd)
        elapsed = time.perf_counter() - t0

        assert result.success is True
        assert result.action == "wait"
        assert "Waited" in result.message
        assert elapsed >= 0.009  # allow small timing tolerance


# ── Element resolution ────────────────────────────────────────────

class TestElementResolution:
    def test_resolve_field_by_aria_label_slug(self, executor, mock_page):
        executor._resolver.resolve_field("field:first_name")
        mock_page.locator.assert_any_call('[aria-label="first_name"]')

    def test_resolve_field_by_aria_label_text(self, executor, mock_page):
        executor._resolver.resolve_field("field:first_name")
        mock_page.locator.assert_any_call('[aria-label="first name"]')

    def test_resolve_field_by_placeholder(self, executor, mock_page):
        mock_page.locator.return_value.count.return_value = 0

        def side_effect(sel):
            loc = _make_locator(count=1 if "placeholder" in sel else 0)
            return loc

        mock_page.locator.side_effect = side_effect

        locator = executor._resolver.resolve_field("field:email")
        assert locator is not None

    def test_resolve_field_by_name(self, executor, mock_page):
        def side_effect(sel):
            loc = _make_locator(count=1 if "name=" in sel else 0)
            return loc

        mock_page.locator.side_effect = side_effect

        locator = executor._resolver.resolve_field("field:email")
        assert locator is not None

    def test_resolve_field_by_id(self, executor, mock_page):
        def side_effect(sel):
            loc = _make_locator(count=1 if sel.startswith("#") else 0)
            return loc

        mock_page.locator.side_effect = side_effect

        locator = executor._resolver.resolve_field("field:email")
        assert locator is not None

    def test_resolve_field_returns_none_when_unmatched(self, executor, mock_page):
        """When no strategy matches, return None (no fallback)."""
        mock_page.locator.return_value.count.return_value = 0

        locator = executor._resolver.resolve_field("field:nonexistent")
        assert locator is None

    def test_resolve_button_by_text(self, executor, mock_page):
        executor._resolver.resolve_button("button:continue")
        mock_page.locator.assert_any_call(
            "button:has-text('continue')"
        )

    def test_resolve_button_returns_none_when_unmatched(self, executor, mock_page):
        mock_page.locator.return_value.count.return_value = 0
        locator = executor._resolver.resolve_button("button:ghost")
        assert locator is None

    def test_resolve_upload_by_aria_label(self, executor, mock_page):
        executor._resolver.resolve_file("upload:resume")
        mock_page.locator.assert_any_call(
            "input[type='file'][aria-label='resume']"
        )

    def test_resolve_upload_returns_none_when_unmatched(self, executor, mock_page):
        mock_page.locator.return_value.count.return_value = 0
        locator = executor._resolver.resolve_file("upload:ghost")
        assert locator is None


# ── ElementResolver generation (shared with Observer) ─────────────

class TestElementResolverGeneration:
    def test_field_id_with_label(self):
        mock_el = MagicMock()
        mock_el.get_attribute.return_value = "First Name"
        res = ElementResolver.__new__(ElementResolver)
        res._used_ids = set()

        fid = res.field_id(mock_el, "First Name", "text")
        assert fid == "field:first_name"

    def test_field_id_deduplication(self):
        mock_el = MagicMock()
        mock_el.get_attribute.return_value = "email"
        res = ElementResolver.__new__(ElementResolver)
        res._used_ids = set()

        fid1 = res.field_id(mock_el, "email", "email")
        fid2 = res.field_id(mock_el, "email", "email")
        assert fid1 == "field:email"
        assert fid2 == "field:email_2"

    def test_button_id(self):
        res = ElementResolver.__new__(ElementResolver)
        res._used_ids = set()
        bid = res.button_id("Continue")
        assert bid == "button:continue"

    def test_file_id(self):
        res = ElementResolver.__new__(ElementResolver)
        res._used_ids = set()
        uid = res.file_id("Upload Resume")
        assert uid == "upload:upload_resume"

    def test_reset_clears_ids(self):
        mock_el = MagicMock()
        mock_el.get_attribute.return_value = "name"
        res = ElementResolver.__new__(ElementResolver)
        res._used_ids = set()

        fid1 = res.field_id(mock_el, "name", "text")
        res.reset()
        fid2 = res.field_id(mock_el, "name", "text")
        assert fid1 == "field:name"
        assert fid2 == "field:name"


# ── Command idempotency / edge cases ──────────────────────────────

class TestEdgeCases:
    def test_fill_with_empty_value(self, executor, mock_page):
        locator = _make_locator(count=1)
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.FILL_FIELD,
            target="field:name",
            value="",
        )
        result = executor.execute(cmd)
        assert result.success is True
        locator.fill.assert_called_once_with("", timeout=10000)

    def test_click_handles_numeric_target(self, executor, mock_page):
        locator = _make_locator(count=1)
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.CLICK_BUTTON,
            target="button:_3",
        )
        result = executor.execute(cmd)
        assert result.success is True

    def test_duration_is_non_negative(self, executor, mock_page):
        locator = _make_locator(count=1)
        mock_page.locator.return_value = locator

        cmd = BrowserCommand(
            action=BrowserAction.FILL_FIELD,
            target="field:x",
            value="y",
        )
        result = executor.execute(cmd)
        assert result.duration_ms >= 0

    def test_execute_fully_unknown_action(self, executor, mock_page):
        cmd = BrowserCommand(action=BrowserAction.FILL_FIELD)
        with patch.object(cmd, "action", object()):
            result = executor.execute(cmd)
        assert result.success is False
