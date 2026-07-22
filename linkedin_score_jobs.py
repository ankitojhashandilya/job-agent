import csv
import json
from urllib.parse import quote_plus, urlsplit, urlunsplit

from playwright.sync_api import Error, TimeoutError, sync_playwright

from browser_session import launch_linkedin_context
from config import (
    JOB_LIMIT,
    JOB_RESULTS_CSV as CSV_OUTPUT,
    JOB_RESULTS_JSON as JSON_OUTPUT,
    SEARCH_KEYWORDS,
    SEARCH_LOCATION,
)
from job_history import update_job_history
from scorer import score_job


def clean_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def build_search_url(keyword: str) -> str:
    return (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={quote_plus(keyword)}"
        f"&location={quote_plus(SEARCH_LOCATION)}"
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


def collect_search_results(page, keyword: str, limit: int) -> list[dict]:
    page.goto(
        build_search_url(keyword),
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


def collect_all_search_results(page, limit: int) -> list[dict]:
    seen_urls = set()
    all_jobs = []

    for keyword in SEARCH_KEYWORDS:
        remaining = limit - len(all_jobs)
        if remaining <= 0:
            break

        keyword_jobs = collect_search_results(
            page,
            keyword,
            remaining,
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


def save_results(results: list[dict]) -> None:
    JSON_OUTPUT.write_text(
        json.dumps(results, indent=2),
        encoding="utf-8",
    )

    columns = [
        "company",
        "title",
        "location",
        "url",
        "search_keyword",
        "match_score",
        "status",
        "reason",
        "matched_skills",
        "missing_skills",
        "technical_fit",
        "seniority",
        "leadership",
        "location_fit",
        "domain_fit",
        "growth_fit",
    ]

    with CSV_OUTPUT.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
        )

        writer.writeheader()

        for result in results:
            row = {key: result.get(key, "") for key in columns}

            row["matched_skills"] = ", ".join(
                result.get("matched_skills", [])
            )
            row["missing_skills"] = ", ".join(
                result.get("missing_skills", [])
            )

            subscores = result.get("subscores", {})
            row["technical_fit"] = subscores.get("technical_fit", 0)
            row["seniority"] = subscores.get("seniority", 0)
            row["leadership"] = subscores.get("leadership", 0)
            row["location_fit"] = subscores.get("location", 0)
            row["domain_fit"] = subscores.get("domain", 0)
            row["growth_fit"] = subscores.get("growth", 0)

            writer.writerow(row)


def main() -> None:
    results = []

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
                JOB_LIMIT,
            )

            print(f"Found {len(summaries)} jobs.")

            for index, summary in enumerate(
                summaries,
                start=1,
            ):
                print(
                    f"[{index}/{len(summaries)}] "
                    f"Reading {summary['title']}..."
                )

                try:
                    job = load_job_details(
                        detail_page,
                        summary,
                    )

                    print(
                        f"  Description length: "
                        f"{len(job['description'])}"
                    )

                    if job["description"]:
                        print(
                            f"  Preview: "
                            f"{job['description'][:250]}..."
                        )
                    else:
                        print(
                            "  WARNING: "
                            "Description extraction failed"
                        )

                    scoring = score_job(job)
                    score = scoring["score"]
                    status = scoring["status"]

                    job.update(
                        {
                            "match_score": score,
                            "status": status,
                            "reason": scoring["reason"],
                            "matched_skills": scoring.get(
                                "matched_skills",
                                [],
                            ),
                            "missing_skills": scoring.get(
                                "missing_skills",
                                [],
                            ),
                            "subscores": scoring.get(
                                "subscores",
                                {},
                            ),
                        }
                    )

                    results.append(job)
                    update_job_history(
                        job,
                        status,
                        "linkedin_score_jobs",
                    )
                    save_results(results)

                    print(f"  Score: {score}")
                    print(f"  Status: {status}")
                    print(
                        f"  Subscores: "
                        f"{scoring.get('subscores', {})}"
                    )
                    print(
                        f"  Matched: "
                        f"{', '.join(scoring.get('matched_skills', []))}"
                    )
                    print(
                        f"  Missing: "
                        f"{', '.join(scoring.get('missing_skills', []))}"
                    )
                    print(
                        f"  Reason: "
                        f"{scoring['reason']}"
                    )

                except Exception as error:
                    print(f"  Skipped because: {error}")

        finally:
            try:
                context.close()
            except Error:
                pass

    save_results(results)

    print(
        f"Saved {len(results)} jobs to "
        f"{JSON_OUTPUT} and {CSV_OUTPUT}"
    )


if __name__ == "__main__":
    main()
