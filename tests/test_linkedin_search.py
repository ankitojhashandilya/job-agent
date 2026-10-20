"""Search-layout regressions using synthetic pages and no live network."""

from unittest.mock import MagicMock

import pytest
from playwright.sync_api import sync_playwright

import discovery
from browser.linkedin_search import LinkedInSearchError, read_search_results


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as runtime:
        instance = runtime.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    context.route("**/*", lambda route: route.fulfill(body="<html><body></body></html>"))
    page.goto("https://www.linkedin.com/jobs/search-results/")
    yield page
    context.close()


def component_card(job_id, title="Senior Data Engineer"):
    return f"""<div role="button" componentkey="job-card-component-ref-{job_id}">
      <div componentkey="job-card-component-ref-{job_id}">
        <p><span>Selected, {title} (Verified job)</span>
          <span aria-hidden="true">{title}</span></p>
        <p>Example Company</p><p>Bengaluru (Hybrid)</p>
      </div></div>"""


def test_current_cards_without_links_produce_canonical_jobs(page):
    page.set_content(component_card(123) + component_card(456, "Staff Engineer"))
    jobs = read_search_results(page, 25)
    assert jobs == [
        {
            "title": "Senior Data Engineer",
            "company": "Example Company",
            "location": "Bengaluru (Hybrid)",
            "url": "https://www.linkedin.com/jobs/view/123/",
        },
        {
            "title": "Staff Engineer",
            "company": "Example Company",
            "location": "Bengaluru (Hybrid)",
            "url": "https://www.linkedin.com/jobs/view/456/",
        },
    ]


def test_classic_cards_are_deduplicated_and_tracking_is_removed(page):
    page.set_content("""<li class="scaffold-layout__list-item"><div class="job-card-container">
      <a href="/jobs/view/123/?trackingId=abc"><strong>Engineer with verification</strong></a>
      <span class="job-card-container__primary-description">Acme</span>
      <span class="job-card-container__metadata-item">Remote</span>
      </div></li>""")
    jobs = read_search_results(page, 25)
    assert len(jobs) == 1
    assert jobs[0] == {
        "title": "Engineer",
        "company": "Acme",
        "location": "Remote",
        "url": "https://www.linkedin.com/jobs/view/123/",
    }


def test_results_wait_for_delayed_cards_and_respect_limit(page):
    page.set_content("<main>Loading jobs...</main>")
    page.evaluate(
        "html => setTimeout(() => document.querySelector('main').innerHTML = html, 200)",
        component_card(123) + component_card(456),
    )
    assert len(read_search_results(page, 1, timeout_ms=3000)) == 1


def test_explicit_empty_search_is_distinct_from_extraction_failure(page):
    page.set_content("<main>No matching jobs found</main>")
    assert read_search_results(page, 25) == []


def test_unrecognised_loading_page_raises_instead_of_returning_zero_jobs(page):
    page.set_content("<main>Loading jobs...</main>")
    with pytest.raises(LinkedInSearchError, match="still be loading"):
        read_search_results(page, 25, timeout_ms=100)


@pytest.mark.parametrize(
    "html,message",
    [
        ('<input type="password"><button>Sign in</button>', "sign-in"),
        ("<main>Security verification: verify you are human</main>", "manual security"),
    ],
)
def test_authentication_and_verification_are_actionable_errors(page, html, message):
    page.set_content(html)
    with pytest.raises(LinkedInSearchError, match=message):
        read_search_results(page, 25)


def test_failed_source_does_not_replace_previous_exports(tmp_path, monkeypatch):
    source = MagicMock()
    source.name = "linkedin"
    source.search.side_effect = LinkedInSearchError("Search layout has changed")
    registry = MagicMock()
    registry.discover.return_value = registry
    registry.active_sources.return_value = [source]
    monkeypatch.setattr(discovery, "SourceRegistry", lambda: registry)
    json_path = tmp_path / "job_results.json"
    csv_path = tmp_path / "job_results.csv"
    json_path.write_text('[{"title":"Previous result"}]', encoding="utf-8")
    csv_path.write_text("title\nPrevious result\n", encoding="utf-8")
    monkeypatch.setattr(discovery, "JOB_RESULTS_JSON", json_path)
    monkeypatch.setattr(discovery, "JOB_RESULTS_CSV", csv_path)
    with pytest.raises(RuntimeError, match="Search layout has changed"):
        discovery.run_discovery()
    assert json_path.read_text(encoding="utf-8") == '[{"title":"Previous result"}]'
    assert csv_path.read_text(encoding="utf-8") == "title\nPrevious result\n"
