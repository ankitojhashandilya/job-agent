from playwright.sync_api import sync_playwright


def main():

    chrome_profile = r"C:\Users\ankit\AppData\Local\Google\Chrome\User Data"

    with sync_playwright() as p:

        browser = p.chromium.launch_persistent_context(
            user_data_dir=chrome_profile,
            headless=False,
            channel="chrome"
        )

        page = browser.new_page()

        page.goto(
            "https://www.linkedin.com/jobs/search/?keywords=Senior%20Data%20Engineer"
        )

        print("Page title:", page.title())

        input("Press Enter to close browser...")

        browser.close()


if __name__ == "__main__":
    main()