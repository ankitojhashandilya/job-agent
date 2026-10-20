"""Real Chromium regressions for the production observe/plan/execute path.

All pages are served by Playwright routes. No live applications or candidate
data are used. Requires ``playwright install chromium``.
"""

import json

import pytest
from playwright.sync_api import sync_playwright

from agent.agent import run_agent
from agent.evidence import make_review_evidence
from agent.execute import BrowserAction, BrowserCommand, ExecutionResult, Executor
from agent.observe import observe_page
from agent.types import TaskInfo


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
    yield page
    context.close()


def load(page, html, *, linkedin=False):
    page.context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
    page.goto(
        "https://www.linkedin.com/jobs/view/123/"
        if linkedin
        else "https://boards.greenhouse.io/acme/jobs/123"
    )


def test_modal_scoping_preserves_duplicate_labels_and_next_in_footer(page):
    load(
        page,
        """
        <header><input aria-label="Search"><a href="/login">Sign in</a></header>
        <main><input aria-label="Email" id="background-email"></main>
        <div role="dialog" aria-label="Apply">
          <label>First Name * <input required id="first-name"></label>
          <label for="email-one">Email</label><input id="email-one" required>
          <label for="email-two">Email</label><input id="email-two" required>
          <footer><button>Next</button></footer>
        </div>
    """,
        linkedin=True,
    )
    snapshot = observe_page(page)
    assert snapshot.page_type == "application_form"
    assert len(snapshot.fields) == 3
    assert any(button.text == "Next" for button in snapshot.buttons)
    executor = Executor(page)
    for field, value in zip(snapshot.fields, ("Ada", "one@example.test", "two@example.test")):
        result = executor.execute(BrowserCommand(BrowserAction.FILL_FIELD, field.id, value))
        assert result.success, result.message
    assert page.locator("#first-name").input_value() == "Ada"
    assert page.locator("#email-one").input_value() == "one@example.test"
    assert page.locator("#email-two").input_value() == "two@example.test"
    assert page.locator("#background-email").input_value() == ""


def test_dropdown_reads_selected_state_and_matches_visible_label(page):
    load(
        page,
        """<main><form>
        <label for="country">Country</label><select id="country" required>
          <option value="" disabled selected>Select a country</option>
          <option value="IN">India</option><option value="GB">United Kingdom</option>
        </select><button>Next</button>
    </form></main>""",
    )
    snapshot = observe_page(page)
    field = snapshot.fields[0]
    assert field.value == ""
    assert {"value": "IN", "label": "India"} in field.options
    result = Executor(page).execute(BrowserCommand(BrowserAction.SELECT_OPTION, field.id, "India"))
    assert result.success, result.message
    assert observe_page(page).fields[0].value == "IN"


def test_observed_element_keeps_its_identity_when_a_field_is_inserted(page):
    load(
        page,
        """<main><form><label>Email<input id="email"></label>
      <button type="button">Next</button></form></main>""",
    )
    field = observe_page(page).fields[0]
    page.locator("form").evaluate(
        "el => el.insertAdjacentHTML('afterbegin', '<input id=unrelated aria-label=Search>')"
    )
    result = Executor(page).execute(
        BrowserCommand(BrowserAction.FILL_FIELD, field.id, "ada@example.test")
    )
    assert result.success, result.message
    assert page.locator("#email").input_value() == "ada@example.test"
    assert page.locator("#unrelated").input_value() == ""


def test_disabled_next_does_not_hide_a_second_enabled_next(page):
    load(
        page,
        """<main><form><button type="button" disabled>Next</button>
      <footer><button type="button" onclick="window.advanced=true">Next</button></footer>
      </form></main>""",
    )
    buttons = observe_page(page).buttons
    assert len(buttons) == 2
    enabled = next(button for button in buttons if button.interactable)
    result = Executor(page).execute(BrowserCommand(BrowserAction.CLICK_BUTTON, enabled.id))
    assert result.success, result.message
    assert page.evaluate("window.advanced === true")


def test_ambiguous_dropdown_answer_is_rejected(page):
    load(
        page,
        """<main><form><label>Country<select required>
      <option value="">Choose country</option>
      <option value="one">India</option><option value="two">India</option>
      </select></label><button type="button">Next</button></form></main>""",
    )
    field = observe_page(page).fields[0]
    result = Executor(page).execute(BrowserCommand(BrowserAction.SELECT_OPTION, field.id, "India"))
    assert not result.success
    assert page.locator("select").input_value() == ""


def test_native_radio_group_can_select_an_explicit_no(page):
    load(
        page,
        """<main><form><fieldset><legend>Work authorization</legend>
        <label><input type="radio" name="auth" required value="y">Yes</label>
        <label><input type="radio" name="auth" required value="n">No</label>
        </fieldset><button type="button">Submit application</button></form></main>""",
    )
    snapshot = observe_page(page)
    assert len(snapshot.fields) == 1
    assert snapshot.fields[0].required
    result = run_agent(page, TaskInfo("", {"work_authorization": "No"}))
    assert result.status == "REVIEW_READY_CANDIDATE", result.reason
    assert page.locator('[value="n"]').is_checked()
    assert result.snapshot.fields[0].value == "n"


@pytest.mark.parametrize("editable", [True, False])
def test_combobox_waits_for_async_options_and_selects_exact_answer(page, editable):
    control = '<input id="country"' if editable else '<button type="button" id="country"'
    ending = ">" if editable else ">Select country</button>"
    load(
        page,
        """<main><form><span id="country-label">Country</span>"""
        + control
        + """
        role="combobox" aria-labelledby="country-label" aria-controls="countries"
        aria-required="true" onclick="showOptions()"
        """
        + ending
        + """
        <button type="button">Submit application</button>
        </form></main><script>
          function showOptions() {
            if (document.getElementById('countries')) return;
            setTimeout(() => {
              const popup = document.createElement('div');
              popup.id = 'countries'; popup.setAttribute('role', 'listbox');
              popup.innerHTML = '<div role="option">India</div><div role="option">Indonesia</div>';
              popup.onclick = (event) => {
                const input = document.getElementById('country');
                if (input.tagName === 'INPUT') input.value = event.target.textContent;
                else { input.textContent = event.target.textContent; input.dataset.value = 'IN'; }
                popup.remove();
              };
              document.body.appendChild(popup);
            }, 300);
          }
        </script>""",
    )
    result = run_agent(page, TaskInfo("", {"country": "India"}))
    assert result.status == "REVIEW_READY_CANDIDATE", result.reason
    assert result.snapshot.fields[0].value in {"India", "IN"}


def test_custom_radio_group_reads_required_and_selected_state(page):
    load(
        page,
        """<main><form>
        <div role="radiogroup" aria-label="Relocation" aria-required="true">
          <button type="button" role="radio" aria-checked="false"
            onclick="this.setAttribute('aria-checked', 'true')">No</button>
        </div><button type="button">Submit application</button>
    </form></main>""",
    )
    result = run_agent(page, TaskInfo("", {"relocation": "No"}))
    assert result.status == "REVIEW_READY_CANDIDATE", result.reason
    assert result.snapshot.fields[0].value == "No"


def test_production_loop_fills_multiple_steps_uploads_hidden_resume_and_stops(page, tmp_path):
    resume = tmp_path / "test-resume.txt"
    resume.write_text("Synthetic test resume", encoding="utf-8")
    load(
        page,
        """
      <header><input placeholder="Search jobs"></header>
      <main><button
        onclick="document.querySelector('[role=dialog]').hidden=false">Easy Apply</button></main>
      <div role="dialog" hidden><form onsubmit="return false">
        <section id="step-one">
          <label>First Name<input required id="first"></label>
          <label>Last Name<input required id="last"></label>
          <label>Email<input required type="email" id="email"></label>
          <footer><button type="button" onclick="
            document.getElementById('step-one').remove();
            document.getElementById('step-two').hidden=false">Next</button></footer>
        </section>
        <section id="step-two" hidden>
          <label>Country<select required><option value="">Select country</option>
            <option value="IN">India</option></select></label>
          <label>Resume<input type="file" style="display:none" required></label>
          <button type="button" onclick="window.didSubmit=true">Submit application</button>
        </section>
      </form></div>
    """,
        linkedin=True,
    )
    result = run_agent(
        page,
        TaskInfo(
            str(resume),
            {
                "first_name": "Ada",
                "last_name": "Example",
                "email": "ada@example.test",
                "country": "India",
            },
        ),
    )
    assert result.status == "REVIEW_READY_CANDIDATE", result.reason
    assert result.resume_uploaded
    assert len(result.fields_filled) == 4
    assert page.evaluate("window.didSubmit === true") is False
    screenshot = tmp_path / "review.png"
    page.screenshot(path=str(screenshot))
    evidence = make_review_evidence(
        result.snapshot,
        application_form_opened=result.application_form_opened,
        resume_uploaded=result.resume_uploaded,
        final_review_detected=result.final_review_detected,
        screenshot_path=str(screenshot),
        timeline=result.timeline,
    )
    assert evidence.verified
    assert "ada@example.test" not in json.dumps(evidence.to_dict())


def test_delayed_popup_becomes_the_active_application_page(page):
    load(
        page,
        """<main><button
          onclick="setTimeout(() => window.open('/application'), 700)">Apply</button></main>""",
    )
    snapshot = observe_page(page)
    executor = Executor(page)
    result = executor.execute(BrowserCommand(BrowserAction.CLICK_BUTTON, snapshot.buttons[0].id))
    assert result.success, result.message
    assert executor.page is not page
    assert executor.page.url.endswith("/application")


def test_known_invalid_field_is_corrected_and_unknown_error_does_not_submit(page):
    load(
        page,
        """<main><form>
      <label>Email<input type="email" value="invalid" required
        oninput="document.getElementById('error').remove()"></label>
      <p id="error" role="alert">Please enter a valid email address</p>
      <button type="button" onclick="window.didSubmit=true">Submit application</button>
    </form></main>""",
    )
    result = run_agent(page, TaskInfo("", {"email": "ada@example.test"}))
    assert result.status == "REVIEW_READY_CANDIDATE", result.reason
    assert page.evaluate("window.didSubmit === true") is False


def test_unknown_required_field_stays_a_human_handoff(page):
    load(
        page,
        """<main><form><label>Custom assessment<textarea required></textarea></label>
      <button type="button" onclick="window.didSubmit=true">Submit application</button>
      </form></main>""",
    )
    result = run_agent(page, TaskInfo("", {"email": "ada@example.test"}))
    assert result.status == "MANUAL_REQUIRED"
    assert page.evaluate("window.didSubmit === true") is False


def test_email_only_authentication_form_remains_a_manual_handoff(page):
    load(
        page,
        """<main><form><label>Email<input required id="email"></label>
      <button type="button">Sign in</button></form></main>""",
    )
    result = run_agent(page, TaskInfo("", {"email": "ada@example.test"}))
    assert result.status == "LOGIN_REQUIRED"
    assert page.locator("#email").input_value() == ""


def test_transient_detachment_recovers_with_a_fresh_observation(page, monkeypatch):
    load(
        page,
        """<main><form><label>Email<input id="email" required></label>
      <button type="button">Submit application</button></form></main>""",
    )
    original = Executor.execute
    attempts = []

    def execute(self, command):
        attempts.append(command.action)
        if len(attempts) == 1:
            page.locator("#email").evaluate("el => el.replaceWith(el.cloneNode(true))")
            return ExecutionResult(False, command.action.value, command.target, "Detached", 0)
        return original(self, command)

    monkeypatch.setattr(Executor, "execute", execute)
    result = run_agent(page, TaskInfo("", {"email": "ada@example.test"}))
    assert result.status == "REVIEW_READY_CANDIDATE", result.reason
    assert len(attempts) == 2
    assert result.timeline[0].result == "failed"


def test_unchanged_form_stops_after_bounded_retries(page):
    load(
        page,
        """<main><form><label>Email<input required oninput="this.value=''"></label>
      <button type="button">Next</button></form></main>""",
    )
    result = run_agent(page, TaskInfo("", {"email": "ada@example.test"}))
    assert result.status == "FAILED"
    assert result.iterations == 3
    assert "No observable progress" in result.reason


def test_failed_combobox_search_is_not_recorded_as_a_completed_answer(page):
    load(
        page,
        """<main><form>
      <input role="combobox" aria-label="Country" aria-controls="missing" required>
      <button type="button">Submit application</button></form></main>""",
    )
    field = observe_page(page).fields[0]
    result = Executor(page).execute(
        BrowserCommand(BrowserAction.SELECT_OPTION, field.id, "India", timeout_ms=300)
    )
    assert not result.success
    assert observe_page(page).fields[0].value == ""


def test_validation_revealed_by_next_is_repaired_using_known_answer(page):
    load(
        page,
        """<main><form>
      <div id="fields"></div>
      <button id="next" type="button" onclick="reveal()">Next</button>
      </form></main><script>
        function reveal() {
          document.getElementById('fields').innerHTML =
            `<label>Email<input type="email" required
              oninput="document.getElementById('error').remove()"></label>
             <p role="alert" id="error">Email is required</p>`;
          document.getElementById('next').textContent = 'Submit application';
          document.getElementById('next').onclick = () => {window.didSubmit=true};
        }
      </script>""",
    )
    # This initially empty step is still an application form (not job details).
    result = run_agent(page, TaskInfo("", {"email": "ada@example.test"}))
    assert result.status == "REVIEW_READY_CANDIDATE", result.reason
    assert page.evaluate("window.didSubmit === true") is False
