from core.models import Job
from sources.base import JobSource, SourceInfo
from sources.manager import SourceManager
from sources.raw import RawJob
from sources.registry import SourceRegistry


class ASource(JobSource):
    info = SourceInfo(name="a", priority=1)

    def search(self, **kwargs) -> list[Job]:
        return [
            self.normalize(
                RawJob(
                    source_name=self.name,
                    url="https://example.com/same",
                    title="first",
                )
            )
        ]

    def normalize(self, raw_job: RawJob) -> Job:
        return self._canonicalize(raw_job)


class BSource(JobSource):
    info = SourceInfo(name="b", priority=2)

    def search(self, **kwargs) -> list[Job]:
        return [
            self.normalize(
                RawJob(
                    source_name=self.name,
                    url="https://example.com/same",
                    title="duplicate",
                )
            ),
            self.normalize(
                RawJob(
                    source_name=self.name,
                    url="https://example.com/unique",
                    title="u",
                )
            ),
        ]

    def normalize(self, raw_job: RawJob) -> Job:
        return self._canonicalize(raw_job)


class Crasher(JobSource):
    info = SourceInfo(name="crasher", priority=3)

    def search(self, **kwargs) -> list[Job]:
        raise RuntimeError("boom")

    def normalize(self, raw_job: RawJob) -> Job:
        return self._canonicalize(raw_job)


def build_manager(*sources) -> SourceManager:
    reg = SourceRegistry(list(sources))
    return SourceManager(reg)


def test_manager_merges_without_dedup():
    """SourceManager returns raw merge; DiscoveryEngine owns dedup."""
    manager = build_manager(ASource(), BSource())

    jobs = manager.search()

    keys = [job.stable_key for job in jobs]
    assert keys == [
        "https://example.com/same",
        "https://example.com/same",
        "https://example.com/unique",
    ]
    assert jobs[0].source == "a"


def test_manager_skips_failing_source():
    manager = build_manager(ASource(), Crasher())

    jobs = manager.search()

    assert len(jobs) == 1
    assert jobs[0].stable_key == "https://example.com/same"
    assert jobs[0].source == "a"
    assert manager.last_errors == {"crasher": "boom"}


def test_manager_injected_dependencies_accessible():
    class FakeBrowser:
        pass

    reg = SourceRegistry()
    manager = SourceManager(reg, browser=FakeBrowser(), cache=object())

    assert isinstance(manager.registry, SourceRegistry)
    assert manager.browser is not None
    assert manager.cache is not None
    assert manager.search() == []
