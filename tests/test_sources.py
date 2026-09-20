from abc import ABC

import pytest

from core.models import Job
from sources.base import JobSource, SourceInfo
from sources.raw import RawJob
from sources.registry import SourceRegistry


class FakeSource(JobSource):
    info = SourceInfo(
        name="fake",
        priority=10,
        supports_remote=True,
        supports_location=True,
    )

    def search(self, **kwargs) -> list[Job]:
        jobs = kwargs.get("jobs", [])
        return [self.normalize(RawJob.from_raw(job, source_name=self.name)) for job in jobs]

    def normalize(self, raw_job: RawJob) -> Job:
        return self._canonicalize(raw_job)


class DisabledSource(JobSource):
    info = SourceInfo(name="disabled", priority=50)

    def search(self, **kwargs) -> list[Job]:
        return []

    def normalize(self, raw_job: RawJob) -> Job:
        return self._canonicalize(raw_job)


def make_raw(title="Engineer", url="https://example.com/j"):
    return RawJob.from_raw(
        {"title": title, "company": "Acme", "url": url},
        source_name="fake",
    )


def test_job_source_is_abc():
    assert issubclass(JobSource, ABC)


def test_incomplete_plugin_cannot_be_instantiated():
    class Incomplete(JobSource):
        pass

    with pytest.raises(TypeError):
        Incomplete()


def test_register_get_contains():
    reg = SourceRegistry()
    registered = reg.register(FakeSource())

    assert registered.name == "fake"
    assert reg.get("fake") is registered
    assert "fake" in reg


def test_empty_name_rejected():
    reg = SourceRegistry()

    class NoName(JobSource):
        info = SourceInfo(name="")

        def search(self, **kwargs) -> list[Job]:
            return []

        def normalize(self, raw_job: RawJob) -> Job:
            return self._canonicalize(raw_job)

    with pytest.raises(ValueError):
        reg.register(NoName())


def test_active_sources_filters_enabled_and_sorts_by_priority():
    reg = SourceRegistry()
    low = FakeSource()
    high = FakeSource()
    high.info = SourceInfo(name="high", priority=1)
    disabled = DisabledSource()
    disabled.enabled = False

    reg.register(low)
    reg.register(high)
    reg.register(disabled)

    names = [s.name for s in reg.active_sources()]
    assert names == ["high", "fake"]


def test_enable_disable_toggle():
    reg = SourceRegistry()
    reg.register(FakeSource())

    reg.disable("fake")
    assert reg.active_sources() == []

    reg.enable("fake")
    assert [s.name for s in reg.active_sources()] == ["fake"]


def test_iteration_and_remove():
    reg = SourceRegistry()
    reg.register(FakeSource())
    assert len(reg) == 1
    assert [s.name for s in reg] == ["fake"]

    reg.remove("fake")
    assert len(reg) == 0
    assert reg.get("fake") is None


def test_normalize_produces_canonical_job():
    source = FakeSource()
    job = source.normalize(make_raw())

    assert isinstance(job, Job)
    assert job.title == "Engineer"
    assert job.company == "Acme"
    assert job.source == "fake"
    assert job.url == "https://example.com/j"


def test_enrich_default_is_pass_through():
    source = FakeSource()
    job = source.normalize(make_raw())
    enriched = source.enrich(job)

    assert enriched is job