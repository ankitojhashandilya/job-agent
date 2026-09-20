from pathlib import Path
from unittest.mock import MagicMock

import browser_session
from login_linkedin import has_authenticated_linkedin_session


def test_linkedin_context_disables_quic(monkeypatch, tmp_path):
    playwright = MagicMock()
    monkeypatch.setattr(browser_session, "PROFILE_DIR", Path(tmp_path) / "profile")

    browser_session.launch_linkedin_context(playwright)

    arguments = playwright.chromium.launch_persistent_context.call_args.kwargs["args"]
    assert "--start-maximized" in arguments
    assert "--disable-quic" in arguments


def test_linkedin_session_check_requires_a_real_authenticated_cookie():
    context = MagicMock()
    context.cookies.return_value = [
        {"name": "JSESSIONID", "value": "opaque"},
        {"name": "li_at", "value": ""},
    ]
    assert has_authenticated_linkedin_session(context) is False

    context.cookies.return_value = [{"name": "li_at", "value": "opaque"}]
    assert has_authenticated_linkedin_session(context) is True
