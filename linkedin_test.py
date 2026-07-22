from playwright.sync_api import Error, sync_playwright

from browser_session import launch_linkedin_context

LOGIN_URL = "https://www.linkedin.com/login"
JOBS_URL = "https://www.linkedin.com/jobs/search/?keywords=Senior%20Data%20Engineer"


with sync_playwright() as p:
    context = launch_linkedin_context(p)
    page = context.pages[0] if context.pages else context.new_page()

    page.goto(JOBS_URL, wait_until="domcontentloaded", timeout=60000)

    if "/login" in page.url or "/checkpoint/" in page.url:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        print(
            "Log in with your LinkedIn email/phone and LinkedIn password. "
            "Do not choose 'Continue with Google' in this automated browser."
        )

    input("Press Enter to close...")

    try:
        context.close()
    except Error:
        # The user may already have closed the Chrome window manually.
        pass
