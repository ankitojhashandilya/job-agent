import json
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import Error, sync_playwright

from browser_session import launch_linkedin_context


SEARCH_URL = "https://www.linkedin.com/jobs/search/?keywords=Senior%20Data%20Engineer"


def clean_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def extract_jobs(page, limit: int = 10) -> list[dict]:
    jobs = page.evaluate(
        """
        () => {
            const cards = [...document.querySelectorAll(
                'li.scaffold-layout__list-item, li.jobs-search-results__list-item, .job-card-container'
            )];
            const seen = new Set();
            return cards.map((card) => {
                const anchor = card.querySelector(
                    'a.job-card-list__title--link, a[href*="/jobs/view/"]'
                );
                if (!anchor) return null;

                const href = anchor.href;
                const titleElement = anchor.querySelector('strong') || anchor;
                const title = titleElement.innerText
                    .split('\\n')[0]
                    .replace(/\\s+with verification$/i, '')
                    .trim();
                const company = (
                    card.querySelector(
                        '.artdeco-entity-lockup__subtitle span, ' +
                        '.job-card-container__primary-description, ' +
                        '.job-card-container__company-name'
                    )?.innerText || ''
                ).trim();
                const location = (
                    card.querySelector(
                        '.artdeco-entity-lockup__caption, ' +
                        '.job-card-container__metadata-item'
                    )?.innerText || ''
                ).trim();

                return { title, company, location, url: href };
            }).filter((job) => {
                if (!job) return false;
                if (!job.url || seen.has(job.url)) return false;
                seen.add(job.url);
                return job.title;
            });
        }
        """
    )

    cleaned = []
    for job in jobs[:limit]:
        cleaned.append(
            {
                "company": job["company"],
                "title": job["title"],
                "location": job["location"],
                "url": clean_url(job["url"]),
            }
        )
    return cleaned


with sync_playwright() as p:
    context = launch_linkedin_context(p)
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    jobs = extract_jobs(page)
    print(json.dumps(jobs, indent=2))

    input("Press Enter to close...")
    try:
        context.close()
    except Error:
        # The user may already have closed the Chrome window manually.
        pass
