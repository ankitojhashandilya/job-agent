from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False
        )

        page = browser.new_page()

        page.goto("https://www.google.com")

        print("Title:", page.title())

        input("Press Enter to close browser...")

        browser.close()

if __name__ == "__main__":
    main()