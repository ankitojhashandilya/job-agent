import csv
import json

from playwright.sync_api import Error, sync_playwright

from browser_session import launch_linkedin_context
from config import (
    JOB_LIMIT,
    JOB_RESULTS_CSV as CSV_OUTPUT,
    JOB_RESULTS_JSON as JSON_OUTPUT,
)
from job_history import update_job_history
from scorer import score_job

from sources.linkedin import (
    LinkedInSource,
    build_search_url,
    clean_url,
    collect_all_search_results,
    collect_search_results,
    description_from_visible_text,
    first_text,
    load_job_details,
)


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
