from agent.cases import ApplicationCase, route_case
from agent.types import PageSnapshot


def snapshot(url: str, page_type: str) -> PageSnapshot:
    return PageSnapshot(url=url, page_title="Test", domain=url.split("/")[2], page_type=page_type)


def test_linkedin_job_detail_routes_to_entry_case():
    assert route_case(
        snapshot("https://www.linkedin.com/jobs/view/123", "job_details")
    ) is ApplicationCase.LINKEDIN_ENTRY


def test_supported_form_routes_to_application_case():
    assert route_case(
        snapshot("https://acme.wd1.myworkdayjobs.com/job/123", "application_form")
    ) is ApplicationCase.APPLICATION_FORM


def test_unknown_site_routes_to_unsupported_case():
    assert route_case(
        snapshot("https://careers.example.org/job/123", "application_form")
    ) is ApplicationCase.UNSUPPORTED


def test_linkedin_profile_share_state_becomes_manual_handoff():
    assert route_case(
        snapshot("https://www.linkedin.com/jobs/view/123", "external_apply_started")
    ) is ApplicationCase.EXTERNAL_HANDOFF
