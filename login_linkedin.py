"""Open the job-agent's persistent Chrome profile for a manual LinkedIn login.

Credentials, MFA codes, and CAPTCHA challenges are intentionally handled only
by the user in the visible browser.  Once the user confirms the session, the
same persistent profile is reused by ``apply_top_jobs.py``.
"""

from playwright.sync_api import sync_playwright

from browser_session import launch_linkedin_context


def has_authenticated_linkedin_session(context) -> bool:
    """Return whether the persistent context has LinkedIn's session cookie.

    The cookie value is never read, displayed, logged, or stored by this
    project.  Its presence is enough to avoid treating an unauthenticated job
    page as a successful manual login.
    """
    try:
        return any(
            cookie.get("name") == "li_at" and bool(cookie.get("value"))
            for cookie in context.cookies(["https://www.linkedin.com"])
        )
    except Exception:
        return False


def main() -> None:
    with sync_playwright() as playwright:
        context = launch_linkedin_context(playwright)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
        print("Chrome is open using the job-agent profile.")
        print("Sign in to LinkedIn and complete any verification in the browser window.")
        while not has_authenticated_linkedin_session(context):
            input(
                "After you are signed in and can see your own LinkedIn feed, "
                "return here and press Enter to verify the session... "
            )
            if not has_authenticated_linkedin_session(context):
                print(
                    "LinkedIn sign-in was not detected yet. Keep the browser open, "
                    "finish sign-in/email verification, then try again."
                )
        context.close()
        print("LinkedIn session verified and saved. You can now run apply_top_jobs.py.")


if __name__ == "__main__":
    main()
