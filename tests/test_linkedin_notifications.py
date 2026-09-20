from agent.observe import _is_linkedin_progress_notice, _normalised_notice_text


def test_linkedin_clicked_apply_notification_is_not_a_validation_error():
    assert _is_linkedin_progress_notice("Job moved to In progress under Clicked apply.")


def test_linkedin_notice_matching_tolerates_browser_whitespace():
    assert _is_linkedin_progress_notice("Job moved to In progress\nunder Clicked apply.")
    assert _normalised_notice_text("  A\n B  ") == "a b"


def test_real_validation_error_is_not_classified_as_linkedin_notification():
    assert not _is_linkedin_progress_notice("Please enter a valid email address.")
