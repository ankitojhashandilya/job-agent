import csv
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error, TimeoutError, sync_playwright

from browser.extraction import (
    classify_page_state,
    current_domain,
    label_text_for_input,
)
from browser_session import launch_linkedin_context
from job_history import already_applied_or_ready, update_job_history


PROJECT_DIR = Path(__file__).resolve().parent
JOB_RESULTS_PATH = PROJECT_DIR / "job_results.json"
APPLICATION_PROFILE_PATH = PROJECT_DIR / "application_profile.json"
APPLICATIONS_JSON = PROJECT_DIR / "applications.json"
APPLICATIONS_CSV = PROJECT_DIR / "applications.csv"
SCREENSHOT_DIR = PROJECT_DIR / "application_screenshots"
TOP_N = 5

FINAL_SUBMIT_PATTERNS = re.compile(
    r"^(submit application|submit|send application)$",
    re.IGNORECASE,
)

NON_FINAL_CONTINUE_PATTERNS = re.compile(
    r"^(next|continue|review|review your application|start|start application)$",
    re.IGNORECASE,
)

EXTERNAL_START_PATTERNS = re.compile(
    r"^(apply now|apply manually|autofill with resume|upload resume|continue|start application)$",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_applications(records: list[dict]) -> None:
    APPLICATIONS_JSON.write_text(json.dumps(records, indent=2), encoding="utf-8")

    columns = [
        "timestamp",
        "company",
        "title",
        "location",
        "url",
        "match_score",
        "apply_type",
        "apply_url",
        "status",
        "resume_uploaded",
        "fields_filled",
        "screenshot",
        "notes",
    ]

    with APPLICATIONS_CSV.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for record in records:
            row = {column: record.get(column, "") for column in columns}
            if isinstance(row["fields_filled"], list):
                row["fields_filled"] = ", ".join(row["fields_filled"])
            writer.writerow(row)


def normalized_score(job: dict) -> int:
    score = int(job.get("match_score") or 0)
    if 1 <= score <= 10:
        return score * 10
    return score


def top_jobs() -> list[dict]:
    jobs = load_json(JOB_RESULTS_PATH, [])
    ranked = sorted(jobs, key=normalized_score, reverse=True)
    return ranked[:TOP_N]


def safe_filename(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_")
    return cleaned[:80] or "application"


def visible_button_by_text(page, pattern: str):
    return page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first


def visible_apply_elements(page) -> list[dict]:
    elements = []
    selectors = [
        "button",
        "a",
        "[role='button']",
    ]

    for selector in selectors:
        try:
            locators = page.locator(selector)
            for index in range(min(locators.count(), 120)):
                element = locators.nth(index)
                try:
                    if not element.is_visible(timeout=500):
                        continue

                    text = re.sub(r"\s+", " ", element.inner_text(timeout=500)).strip()
                    aria = element.get_attribute("aria-label", timeout=500) or ""
                    href = element.get_attribute("href", timeout=500) or ""
                    label = text or aria

                    if re.search(r"apply|easy apply", f"{label} {href}", re.IGNORECASE):
                        elements.append(
                            {
                                "selector": selector,
                                "index": index,
                                "text": text,
                                "aria": aria,
                                "href": href,
                            }
                        )
                except Exception:
                    continue
        except Exception:
            continue

    return elements


def click_element(element) -> bool:
    try:
        element.scroll_into_view_if_needed(timeout=2000)
        element.click(timeout=5000)
        return True
    except Exception:
        return False


def click_apply(page) -> str:
    selectors = [
        "button",
        "a",
        "[role='button']",
    ]

    for selector in selectors:
        try:
            elements = page.locator(selector)
            for index in range(min(elements.count(), 120)):
                element = elements.nth(index)
                try:
                    if not element.is_visible(timeout=1000) or not element.is_enabled(timeout=1000):
                        continue

                    text = re.sub(r"\s+", " ", element.inner_text(timeout=1000)).strip()
                    aria = element.get_attribute("aria-label", timeout=1000) or ""
                    href = element.get_attribute("href", timeout=1000) or ""
                    label = f"{text} {aria} {href}".strip()

                    if re.search(r"\beasy apply\b", label, re.IGNORECASE):
                        if click_element(element):
                            page.wait_for_timeout(3000)
                            return "easy_apply"

                    if re.search(r"\bapply\b", label, re.IGNORECASE):
                        if click_element(element):
                            page.wait_for_timeout(3000)
                            return "external_or_standard"
                except Exception:
                    continue
        except Exception:
            continue

    return "not_found"


def upload_resume(page, resume_path: Path) -> bool:
    if not resume_path.exists():
        return False

    try:
        file_inputs = page.locator('input[type="file"]')
        count = file_inputs.count()
        for index in range(count):
            file_inputs.nth(index).set_input_files(str(resume_path), timeout=5000)
            page.wait_for_timeout(1000)
            return True
    except Exception:
        return False

    return False


def click_first_non_final_continue(page) -> str:
    try:
        buttons = page.locator("button")
        for index in range(buttons.count()):
            button = buttons.nth(index)
            try:
                if not button.is_visible(timeout=1000) or not button.is_enabled(timeout=1000):
                    continue

                text = button.inner_text(timeout=1000).strip()
                if not text:
                    continue

                if FINAL_SUBMIT_PATTERNS.search(text):
                    return ""

                if NON_FINAL_CONTINUE_PATTERNS.search(text):
                    button.click(timeout=5000)
                    page.wait_for_timeout(2500)
                    return text
            except Exception:
                continue
    except Exception:
        return ""

    return ""


def click_cookie_buttons(page) -> list[str]:
    clicked = []
    patterns = [
        r"^Accept Cookies$",
        r"^Accept All$",
        r"^Accept all cookies$",
        r"^I Accept$",
    ]

    for pattern in patterns:
        try:
            button = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first
            if button.count() and button.is_visible(timeout=1000):
                button.click(timeout=3000)
                page.wait_for_timeout(1000)
                clicked.append(pattern.strip("^$"))
                break
        except Exception:
            continue

    return clicked


def click_external_start_action(page) -> str:
    try:
        controls = page.locator("button, a, [role='button']")
        for index in range(min(controls.count(), 160)):
            control = controls.nth(index)
            try:
                if not control.is_visible(timeout=1000) or not control.is_enabled(timeout=1000):
                    continue

                text = re.sub(r"\s+", " ", control.inner_text(timeout=1000)).strip()
                aria = control.get_attribute("aria-label", timeout=1000) or ""
                label = text or aria

                if not label or FINAL_SUBMIT_PATTERNS.search(label):
                    continue

                if EXTERNAL_START_PATTERNS.search(label):
                    if click_element(control):
                        page.wait_for_timeout(3000)
                        return label
            except Exception:
                continue
    except Exception:
        return ""

    return ""



def advance_external_apply(page, resume_path: Path, candidate: dict) -> tuple[bool, list[str], list[str], str]:
    resume_uploaded = False
    fields_filled = []
    notes = []
    page_state = "open"

    clicked_cookies = click_cookie_buttons(page)
    if clicked_cookies:
        notes.append("Clicked cookie button: " + ", ".join(clicked_cookies))

    for step in range(1, 6):
        page_state = classify_page_state(page)
        if page_state in {"account_required", "job_unavailable", "job_apply_redirect_lost"}:
            notes.append(f"Page state: {page_state}")
            break

        if upload_resume(page, resume_path):
            resume_uploaded = True

        fields_filled.extend(fill_safe_fields(page, candidate))

        final_buttons = detect_final_submit_buttons(page)
        if final_buttons:
            notes.append("Stopped before final submit button: " + ", ".join(final_buttons))
            break

        clicked = click_external_start_action(page)
        if clicked:
            notes.append(f"Clicked external start button: {clicked}")
            continue

        if resume_uploaded or fields_filled:
            notes.append(f"No further safe external action found at step {step}.")
        else:
            notes.append(f"No visible resume upload or safe start action found at step {step}.")
        break

    return resume_uploaded, sorted(set(fields_filled)), notes, page_state



def value_for_label(label: str, candidate: dict) -> tuple[str, str] | tuple[None, None]:
    lowered = label.lower()

    mapping = [
        ("first_name", ["first name"]),
        ("last_name", ["last name", "surname"]),
        ("full_name", ["full name", "name"]),
        ("email", ["email"]),
        ("phone", ["phone", "mobile"]),
        ("city", ["city"]),
        ("country", ["country"]),
        ("current_company", ["current company", "company"]),
        ("current_title", ["current title", "current role", "job title"]),
        ("years_of_experience", ["years of experience", "total experience", "experience"]),
        ("notice_period", ["notice period"]),
        ("current_ctc", ["current ctc", "current salary"]),
        ("expected_ctc", ["expected ctc", "expected salary"]),
        ("linkedin_url", ["linkedin"]),
        ("github_url", ["github"]),
        ("portfolio_url", ["portfolio", "website"]),
    ]

    for key, needles in mapping:
        if any(needle in lowered for needle in needles):
            value = str(candidate.get(key, "")).strip()
            if value:
                return key, value

    return None, None


def fill_safe_fields(page, candidate: dict) -> list[str]:
    filled = []
    selectors = [
        "input:not([type='hidden']):not([type='file']):not([type='checkbox']):not([type='radio'])",
        "textarea",
    ]

    for selector in selectors:
        fields = page.locator(selector)
        try:
            count = fields.count()
        except Exception:
            continue

        for index in range(count):
            field = fields.nth(index)
            try:
                if not field.is_visible(timeout=1000) or not field.is_enabled(timeout=1000):
                    continue

                existing = field.input_value(timeout=1000) if selector.startswith("input") else field.inner_text(timeout=1000)
                if existing.strip():
                    continue

                label = label_text_for_input(field)
                key, value = value_for_label(label, candidate)
                if not key or not value:
                    continue

                field.fill(value, timeout=3000)
                filled.append(key)
            except Exception:
                continue

    return sorted(set(filled))


def advance_easy_apply(page, resume_path: Path, candidate: dict) -> tuple[bool, list[str], list[str]]:
    resume_uploaded = False
    fields_filled = []
    notes = []

    for step in range(1, 7):
        if upload_resume(page, resume_path):
            resume_uploaded = True

        fields_filled.extend(fill_safe_fields(page, candidate))

        final_buttons = detect_final_submit_buttons(page)
        if final_buttons:
            notes.append("Stopped before final submit button: " + ", ".join(final_buttons))
            break

        clicked = click_first_non_final_continue(page)
        if not clicked:
            notes.append(f"No safe next/review button found at step {step}.")
            break

        notes.append(f"Clicked non-final button: {clicked}")

    return resume_uploaded, sorted(set(fields_filled)), notes


def detect_final_submit_buttons(page) -> list[str]:
    labels = []
    try:
        buttons = page.locator("button")
        for index in range(buttons.count()):
            text = buttons.nth(index).inner_text(timeout=1000).strip()
            if text and FINAL_SUBMIT_PATTERNS.search(text):
                labels.append(text)
    except Exception:
        pass
    return labels



def process_job(context, job: dict, profile: dict, existing_records: list[dict]) -> dict:
    page = context.new_page()
    resume_path = Path(profile.get("resume_path", ""))
    candidate = profile.get("candidate", {})
    screenshot_path = ""
    notes = []
    apply_type = "unknown"
    resume_uploaded = False
    fields_filled = []
    status = "started"
    final_apply_url = ""

    try:
        page.goto(job["url"], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        pages_before = set(context.pages)
        apply_type = click_apply(page)

        if apply_type == "not_found":
            status = "apply_button_not_found"
            notes.append("No visible Apply or Easy Apply button found.")
            candidates = visible_apply_elements(page)
            if candidates:
                notes.append("Apply-like elements seen: " + json.dumps(candidates[:5]))
        else:
            page.wait_for_timeout(3000)

            new_pages = [candidate_page for candidate_page in context.pages if candidate_page not in pages_before]
            if new_pages:
                page = new_pages[-1]
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                apply_type = "external"
                notes.append(f"Opened external apply domain: {current_domain(page)}")

            if not resume_path.exists():
                status = "needs_resume"
                notes.append(f"Resume not found: {resume_path}")
            elif apply_type == "easy_apply":
                resume_uploaded, fields_filled, easy_apply_notes = advance_easy_apply(
                    page,
                    resume_path,
                    candidate,
                )
                notes.extend(easy_apply_notes)
            else:
                (
                    resume_uploaded,
                    fields_filled,
                    external_notes,
                    page_state,
                ) = advance_external_apply(
                    page,
                    resume_path,
                    candidate,
                )
                notes.extend(external_notes)
                if page_state in {
                    "account_required",
                    "job_unavailable",
                    "job_apply_redirect_lost",
                }:
                    status = page_state

            if profile.get("safe_autofill", True) and apply_type != "easy_apply":
                fields_filled = sorted(
                    set(fields_filled + fill_safe_fields(page, candidate))
                )

            final_buttons = detect_final_submit_buttons(page)
            if final_buttons:
                notes.append("Stopped before final submit button: " + ", ".join(final_buttons))

            if status not in {
                "needs_resume",
                "account_required",
                "job_unavailable",
                "job_apply_redirect_lost",
            }:
                status = "ready_for_review"

        SCREENSHOT_DIR.mkdir(exist_ok=True)
        screenshot_file = (
            SCREENSHOT_DIR
            / f"{safe_filename(job.get('company', 'company'))}_{safe_filename(job.get('title', 'job'))}.png"
        )
        page.screenshot(path=str(screenshot_file), full_page=True)
        screenshot_path = str(screenshot_file)
        final_apply_url = page.url

    except Exception as error:
        status = "error"
        notes.append(str(error))
        try:
            final_apply_url = page.url
        except Exception:
            final_apply_url = ""
    finally:
        try:
            page.close()
        except Exception:
            pass

    return {
        "timestamp": now_iso(),
        "company": job.get("company", ""),
        "title": job.get("title", ""),
        "location": job.get("location", ""),
        "url": job.get("url", ""),
        "match_score": normalized_score(job),
        "apply_type": apply_type,
        "apply_url": final_apply_url,
        "status": status,
        "resume_uploaded": resume_uploaded,
        "fields_filled": fields_filled,
        "screenshot": screenshot_path,
        "notes": " | ".join(notes),
    }


def main() -> None:
    if not JOB_RESULTS_PATH.exists():
        raise SystemExit("Missing job_results.json. Run linkedin_score_jobs.py first.")

    profile = load_json(APPLICATION_PROFILE_PATH, {})
    jobs = top_jobs()
    if not jobs:
        raise SystemExit("No jobs found in job_results.json.")

    existing_records = load_json(APPLICATIONS_JSON, [])
    retryable_statuses = {
        "apply_button_not_found",
        "error",
        "job_apply_redirect_lost",
    }
    already_started = {
        record.get("url")
        for record in existing_records
        if (
            record.get("status") not in retryable_statuses
            and not (
                record.get("status") == "ready_for_review"
                and not record.get("resume_uploaded")
            )
        )
    }
    pending_jobs = [
        job
        for job in jobs
        if job.get("url") not in already_started
        and not already_applied_or_ready(job.get("url", ""))
    ]

    print(f"Top jobs available: {len(jobs)}")
    print(f"Pending applications this run: {len(pending_jobs)}")
    print("The script will stop before final submission for every job.")

    with sync_playwright() as playwright:
        context = launch_linkedin_context(playwright)

        try:
            for index, job in enumerate(pending_jobs, start=1):
                print(f"[{index}/{len(pending_jobs)}] Preparing {job.get('company')} - {job.get('title')}")
                record = process_job(context, job, profile, existing_records)
                existing_records.append(record)
                update_job_history(
                    job,
                    record.get("status", ""),
                    "apply_top_jobs",
                )
                save_applications(existing_records)
                print(f"  Status: {record['status']}")
                print(f"  Notes: {record['notes'] or 'None'}")
        finally:
            try:
                context.close()
            except Error:
                pass

    save_applications(existing_records)
    print(f"Saved metadata to {APPLICATIONS_JSON} and {APPLICATIONS_CSV}")


if __name__ == "__main__":
    main()
