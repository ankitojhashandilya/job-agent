"""LinkedIn job-source plugin.

Relocated from ``linkedin_score_jobs.py``. The scraping functions in this
module are byte-for-byte identical to the originals; only their home
module changed. They contain **only** browser automation — no scoring,
no history writing, no persistence. Scoring, history, and persistence live
in ``discovery.py``/the caller.

``linkedin_score_jobs.py`` re-exports these functions so the legacy public
API and pipeline continue working unchanged.
"""

from __future__ import annotations

from urllib.parse import quote_plus, urlsplit, urlunsplit
from typing import Any

from playwright.sync_api import Error, TimeoutError, sync_playwright

from browser_session import launch_linkedin_context
from config import (
    JOB_LIMIT,
    SEARCH_KEYWORDS,
    SEARCH_LOCATION,
)
from core.models import Job
from sources.base import JobSource, SourceInfo
from sources.raw import RawJob


def clean_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def build_search_url(keyword: str, location: str | None = None) -> str:
    """Build a LinkedIn search URL using an explicit location when supplied."""
    search_location = location or SEARCH_LOCATION
    return (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={quote_plus(keyword)}"
        f"&location={quote_plus(search_location)}"
    )


def first_text(page, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                text = locator.inner_text(timeout=3000).strip()
                if text:
                    return text
        except (Error, TimeoutError):
            continue
    return ""


def description_from_visible_text(page) -> str:
    try:
        body_text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return ""

    markers = [
        "About the job",
        "About the Job",
        "Job description",
        "Job Description",
    ]

    start = -1
    for marker in markers:
        start = body_text.find(marker)
        if start != -1:
            start += len(marker)
            break

    if start == -1:
        return ""

    description = body_text[start:]

    end_markers = [
        "\nShow less",
        "\nShow more",
        "\nSkills",
        "\nMeet the hiring team",
        "\nPeople you can reach out to",
        "\nSet alert",
        "\nSimilar jobs",
    ]

    end_positions = [
        description.find(marker)
        for marker in end_markers
        if description.find(marker) > 0
    ]

    if end_positions:
        description = description[: min(end_positions)]

    lines = [
        line.strip()
        for line in description.splitlines()
        if line.strip()
    ]

    return "\n".join(lines).strip()


def collect_search_results(
    page,
    keyword: str,
    limit: int,
    location: str | None = None,
) -> list[dict]:
    page.goto(
        build_search_url(keyword, location),
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(5000)

    jobs = page.evaluate(
        """
        (limit) => {
            const cards = [...document.querySelectorAll(
                'li.scaffold-layout__list-item, li.jobs-search-results__list-item, .job-card-container'
            )];

            const seen = new Set();
            const results = [];

            for (const card of cards) {
                const link = card.querySelector(
                    'a.job-card-list__title--link, a[href*="/jobs/view/"]'
                );

                if (!link || seen.has(link.href)) {
                    continue;
                }

                seen.add(link.href);

                const titleNode = link.querySelector('strong') || link;

                const title = titleNode.innerText
                    .split('\\n')[0]
                    .replace(/\\s+with verification$/i, '')
                    .trim();

                const company = (
                    card.querySelector(
                        '.artdeco-entity-lockup__subtitle span,' +
                        '.job-card-container__primary-description,' +
                        '.job-card-container__company-name'
                    )?.innerText || ''
                ).trim();

                const location = (
                    card.querySelector(
                        '.artdeco-entity-lockup__caption,' +
                        '.job-card-container__metadata-item'
                    )?.innerText || ''
                ).trim();

                if (title) {
                    results.push({
                        title,
                        company,
                        location,
                        url: link.href
                    });
                }

                if (results.length >= limit) {
                    break;
                }
            }

            return results;
        }
        """,
        limit,
    )

    for job in jobs:
        job["url"] = clean_url(job["url"])
        job["search_keyword"] = keyword

    return jobs


def collect_all_search_results(
    page,
    limit: int,
    keywords: list[str] | None = None,
    location: str | None = None,
) -> list[dict]:
    seen_urls = set()
    all_jobs = []

    for keyword in keywords or SEARCH_KEYWORDS:
        remaining = limit - len(all_jobs)
        if remaining <= 0:
            break

        keyword_jobs = collect_search_results(
            page,
            keyword,
            remaining,
            location,
        )

        print(
            f"Found {len(keyword_jobs)} raw jobs "
            f"for keyword: {keyword}"
        )

        for job in keyword_jobs:
            if job["url"] in seen_urls:
                continue

            seen_urls.add(job["url"])
            all_jobs.append(job)

            if len(all_jobs) >= limit:
                break

    return all_jobs


def load_job_details(page, summary: dict) -> dict:
    page.goto(
        summary["url"],
        wait_until="domcontentloaded",
        timeout=60000,
    )

    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    page.wait_for_timeout(3000)

    # Expand job description if collapsed
    try:
        show_more = page.locator(
            'button:has-text("Show more"), button[aria-label*="Show more"]'
        ).first

        if show_more.count() > 0 and show_more.is_visible():
            show_more.click(timeout=2000)
            page.wait_for_timeout(1000)

    except Exception:
        pass

    title = first_text(
        page,
        [
            "h1",
            ".job-details-jobs-unified-top-card__job-title",
            ".jobs-unified-top-card__job-title",
        ],
    )

    company = first_text(
        page,
        [
            ".job-details-jobs-unified-top-card__company-name",
            ".jobs-unified-top-card__company-name",
        ],
    )

    location = first_text(
        page,
        [
            ".job-details-jobs-unified-top-card__primary-description-container",
            ".jobs-unified-top-card__bullet",
        ],
    )

    description = ""

    description_selectors = [
        "#job-details",
        ".jobs-description-content__text",
        ".jobs-description__content",
        ".jobs-box__html-content",
    ]

    for selector in description_selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                text = locator.inner_text(timeout=5000).strip()
                if len(text) > 300:
                    description = text
                    break
        except Exception:
            continue

    # Retry after scrolling
    if len(description) < 300:
        try:
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(2000)

            for selector in description_selectors:
                try:
                    locator = page.locator(selector).first
                    if locator.count() > 0:
                        text = locator.inner_text(timeout=5000).strip()
                        if len(text) > 300:
                            description = text
                            break
                except Exception:
                    continue
        except Exception:
            pass

    if len(description) < 300:
        fallback_description = description_from_visible_text(page)
        if len(fallback_description) > len(description):
            description = fallback_description

    return {
        "company": company or summary["company"],
        "title": title or summary["title"],
        "location": location or summary["location"],
        "url": summary["url"],
        "search_keyword": summary.get("search_keyword", ""),
        "description": description[:15000],
    }


class LinkedInSource(JobSource):
    """LinkedIn job source plugin.

    Attributes:
        limit: Number of jobs to collect (defaults to ``config.JOB_LIMIT``).
    """

    info = SourceInfo(
        name="linkedin",
        supports_location=True,
        requires_login=True,
        priority=10,
    )

    def __init__(self, limit: int | None = None, **kwargs: Any) -> None:
        """Initialize the LinkedIn source.

        Args:
            limit: Optional per-run job cap; defaults to ``config.JOB_LIMIT``.
            **kwargs: Accepted for future constructor config.
        """
        super().__init__()
        self.limit = limit if limit is not None else JOB_LIMIT

    def normalize(self, raw_job: RawJob) -> Job:
        """Convert a raw LinkedIn record to a canonical :class:`Job`.

        Args:
            raw_job: The raw LinkedIn record.

        Returns:
            A canonical :class:`core.models.Job`.
        """
        return self._canonicalize(raw_job)

    def search(self, **kwargs: Any) -> list[Job]:
        """Discover jobs by running the identical LinkedIn scraping routine.

        Opens a persistent Chrome context, collects search results for each
        configured keyword, loads each job's detail page, and returns
        canonical :class:`Job` objects. Does **not** score or persist —
        that is the caller's responsibility.

        Args:
            **kwargs: Optional ``limit`` override.

        Returns:
            A list of canonical :class:`Job` instances.
        """
        requested_limit = kwargs.get("limit")
        limit = self.limit if requested_limit is None else int(requested_limit)
        if limit <= 0:
            return []

        requested_keywords = kwargs.get("keywords")
        if requested_keywords is None:
            keywords = list(SEARCH_KEYWORDS)
        elif isinstance(requested_keywords, str):
            keywords = [requested_keywords]
        else:
            keywords = [str(keyword) for keyword in requested_keywords if str(keyword).strip()]

        location = kwargs.get("location") or SEARCH_LOCATION
        jobs: list[Job] = []

        with sync_playwright() as playwright:
            context = launch_linkedin_context(playwright)

            search_page = (
                context.pages[0]
                if context.pages
                else context.new_page()
            )
            detail_page = context.new_page()

            try:
                summaries = collect_all_search_results(
                    search_page,
                    limit,
                    keywords=keywords,
                    location=location,
                )

                print(f"Found {len(summaries)} jobs.")

                for index, summary in enumerate(summaries, start=1):
                    print(
                        f"[{index}/{len(summaries)}] "
                        f"Reading {summary['title']}..."
                    )

                    try:
                        detail = load_job_details(detail_page, summary)
                        raw = RawJob.from_raw(detail, source_name=self.name)
                        jobs.append(self.normalize(raw))
                    except Exception as error:
                        print(f"  Skipped because: {error}")
            finally:
                try:
                    context.close()
                except Error:
                    pass

        return jobs


__all__ = [
    "clean_url",
    "build_search_url",
    "first_text",
    "description_from_visible_text",
    "collect_search_results",
    "collect_all_search_results",
    "load_job_details",
    "LinkedInSource",
]
