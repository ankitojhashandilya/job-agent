from core.models import Job
from sources.base import JobSource, SourceInfo
from sources.discovery import DiscoveryEngine
from sources.raw import RawJob
from sources.registry import SourceRegistry
from sources.manager import SourceManager


class ASource(JobSource):
    info = SourceInfo(name="a", priority=1)

    def search(self, **kwargs) -> list[Job]:
        return [
            self._mk("https://example.com/same", "first"),
            self._mk("https://example.com/only-a", "only-a"),
        ]

    def normalize(self, raw_job: RawJob) -> Job:
        return self._canonicalize(raw_job)

    def _mk(self, url: str, title: str) -> Job:
        return self._canonicalize(
            RawJob(
                source_name=self.name,
                url=url,
                title=title,
                company="Acme",
            )
        )


class BSource(JobSource):
    info = SourceInfo(name="b", priority=2)

    def search(self, **kwargs) -> list[Job]:
        return [
            self._mk("https://example.com/same", "duplicate"),
            self._mk("https://example.com/only-b", "only-b"),
        ]

    def normalize(self, raw_job: RawJob) -> Job:
        return self._canonicalize(raw_job)

    def _mk(self, url: str, title: str) -> Job:
        return self._canonicalize(
            RawJob(
                source_name=self.name,
                url=url,
                title=title,
                company="Globex",
            )
        )


def build_engine(*sources) -> DiscoveryEngine:
    registry = SourceRegistry(list(sources))
    return DiscoveryEngine(SourceManager(registry))


def test_discovery_merges_and_deduplicates_across_sources():
    engine = build_engine(ASource(), BSource())

    jobs = engine.discover()

    keys = [job.stable_key for job in jobs]
    assert keys == [
        "https://example.com/same",
        "https://example.com/only-a",
        "https://example.com/only-b",
    ]
    assert jobs[0].title == "first"  # first encounter wins


def test_discovery_sorts_by_key():
    engine = build_engine(ASource())

    jobs = engine.discover(sort_key=lambda job: job.title)

    assert [job.title for job in jobs] == ["first", "only-a"]


def test_discovery_reverses_with_custom_sort():
    engine = build_engine(BSource())

    jobs = engine.discover(sort_key=lambda job: job.title, reverse=True)

    assert jobs[0].title == "only-b"