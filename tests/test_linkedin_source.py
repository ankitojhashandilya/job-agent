"""Step 3: LinkedIn plugin relocation — behavior must be unchanged."""

import textwrap

import pytest

from core.models import Job
from sources.base import JobSource
from sources.linkedin import (
    LinkedInSource,
    build_search_url,
    clean_url,
    description_from_visible_text,
)
from sources.raw import RawJob


def test_source_is_a_job_source_plugin():
    assert issubclass(LinkedInSource, JobSource)
    assert LinkedInSource.info.name == "linkedin"


def test_source_metadata_capabilities():
    assert LinkedInSource.info.supports_location is True
    assert LinkedInSource.info.requires_login is True
    assert LinkedInSource.info.priority == 10


def test_source_default_limit():
    source = LinkedInSource()
    assert source.limit is not None
    assert source.limit > 0


def test_clean_and_build_urls_unchanged():
    assert clean_url("https://a.example.com/x?y=1#z") == "https://a.example.com/x"
    url = build_search_url("Data Engineer")
    assert "keywords=Data+Engineer" in url
    assert url.startswith("https://www.linkedin.com/jobs/search/")


def test_description_from_visible_text():
    body = textwrap.dedent(
        """\
        Some header text
        About the job
        We need a Data Engineer.
        Skills
        Python
        """
    )
    result = description_from_visible_text(_FakePage(body))
    assert "We need a Data Engineer." in result
    assert "Skills" not in result


def test_normalize_produces_canonical_job_from_linkedin_dict():
    source = LinkedInSource()
    raw = RawJob.from_raw(
        {
            "title": "Lead Data Engineer",
            "company": "Acme",
            "location": "Bangalore, India",
            "url": "https://www.linkedin.com/jobs/view/123",
            "description": "A role description",
        },
        source_name="linkedin",
    )
    job = source.normalize(raw)

    assert isinstance(job, Job)
    assert job.title == "Lead Data Engineer"
    assert job.source == "linkedin"


class _FakePage:
    def __init__(self, body: str) -> None:
        self._body = body

    def locator(self, selector):
        return _FakeLocator(self._body)


class _FakeLocator:
    def __init__(self, body: str) -> None:
        self._body = body

    def inner_text(self, timeout=None) -> str:
        return self._body


def test_public_api_preserved_in_legacy_script():
    import linkedin_score_jobs
    import sources.linkedin as plugin

    names = [
        "clean_url",
        "build_search_url",
        "first_text",
        "description_from_visible_text",
        "collect_search_results",
        "collect_all_search_results",
        "load_job_details",
    ]
    for name in names:
        assert hasattr(linkedin_score_jobs, name), f"{name} missing from legacy script"
        assert getattr(linkedin_score_jobs, name) is getattr(plugin, name), f"{name} differs"


def test_plugin_discovers_in_registry():
    from sources.registry import SourceRegistry

    reg = SourceRegistry()
    reg.discover(package="sources")

    discovered = reg.get("linkedin")
    assert discovered is not None
    assert discovered.name == "linkedin"


def test_source_accepts_pipeline_default_limit_and_forwards_query_overrides(monkeypatch):
    from unittest.mock import MagicMock

    from sources.linkedin import LinkedInSource

    source = LinkedInSource(limit=7)
    context = MagicMock()
    context.pages = [MagicMock()]

    playwright = MagicMock()
    monkeypatch.setattr("sources.linkedin.sync_playwright", MagicMock())
    from sources import linkedin

    linkedin.sync_playwright.return_value.__enter__.return_value = playwright
    monkeypatch.setattr("sources.linkedin.launch_linkedin_context", lambda _: context)
    collect = MagicMock(return_value=[])
    monkeypatch.setattr("sources.linkedin.collect_all_search_results", collect)

    assert source.search(limit=None, keywords=["Staff Data Engineer"], location="Remote") == []
    collect.assert_called_once_with(
        context.pages[0],
        7,
        keywords=["Staff Data Engineer"],
        location="Remote",
    )
