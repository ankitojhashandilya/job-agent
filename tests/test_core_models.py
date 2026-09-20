from core.models import Application, Job


def test_job_round_trip_from_pipeline_dict():
    payload = {
        "title": "Lead Data Engineer",
        "company": "Acme",
        "location": "Bangalore, India",
        "url": "https://example.com/job/1",
        "description": "A role",
    }
    job = Job.from_dict(payload)

    assert job.title == "Lead Data Engineer"
    assert job.company == "Acme"
    assert job.location == "Bangalore, India"
    assert job.url == "https://example.com/job/1"
    assert job.stable_key == "https://example.com/job/1"


def test_job_roundtrip_from_applied_record_dict():
    job = Job.from_dict(
        {
            "job_title": "Staff Data Engineer",
            "company": "Globex",
            "job_location": "Remote",
            "url": "https://example.com/job/2",
            "job_id": "id-42",
        }
    )

    assert job.title == "Staff Data Engineer"
    assert job.location == "Remote"
    assert job.source_job_id == "id-42"

    restored = Job.from_dict(job.to_dict())
    assert restored.title == job.title
    assert restored.company == job.company


def test_application_roundtrip_from_record():
    record = {
        "timestamp": "2026-08-02T10:00:00",
        "company": "Acme",
        "title": "Lead Data Engineer",
        "location": "Bangalore, India",
        "url": "https://example.com/job/1",
        "match_score": 95,
        "apply_type": "easy_apply",
        "apply_url": "https://example.com/apply",
        "status": "READY_FOR_REVIEW",
        "resume_uploaded": True,
        "fields_filled": ["email", "phone"],
        "screenshot": "shot.png",
        "notes": "done",
    }
    application = Application.from_record(record)

    assert application.job.title == "Lead Data Engineer"
    assert application.job.company == "Acme"
    assert application.match_score == 95
    assert application.status == "READY_FOR_REVIEW"
    assert application.resume_uploaded is True

    restored = Application.from_record(application.to_record())
    assert restored.to_record()["url"] == application.job.url
    assert restored.status == "READY_FOR_REVIEW"


def test_application_defaults():
    application = Application()

    assert application.match_score == 0
    assert application.resume_uploaded is False
    assert application.fields_filled == []
    assert application.job.stable_key == ""