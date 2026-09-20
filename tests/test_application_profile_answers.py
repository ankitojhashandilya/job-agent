import apply_top_jobs


def test_candidate_values_merges_explicit_application_answers():
    values = apply_top_jobs.candidate_values(
        {
            "candidate": {"email": "person@example.com", "notice_period": ""},
            "application_answers": {"work_authorization": "Yes", "notice_period": "30 days"},
        }
    )

    assert values["email"] == "person@example.com"
    assert values["work_authorization"] == "Yes"
    assert values["notice_period"] == "30 days"


def test_candidate_values_ignores_invalid_answer_structure():
    assert apply_top_jobs.candidate_values({"candidate": [], "application_answers": []}) == {}
