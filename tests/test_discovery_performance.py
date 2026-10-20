import json
import sqlite3
import time
from unittest.mock import MagicMock

import pytest

import discovery
import discovery_cache
import scorer
from core.models import Job
from core.persistence import write_text_atomic
from discovery_cache import DiscoveryCache, discovery_lock


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery_cache, "CACHE_PATH", tmp_path / "cache.sqlite3")
    return DiscoveryCache()


def test_cache_roundtrip_expiration_and_invalid_data(cache):
    cache.put("details", "job", {"description": "Example"})
    assert cache.get("details", "job", 3600) == {"description": "Example"}
    with sqlite3.connect(cache.path) as connection:
        connection.execute("UPDATE entries SET updated=?", (time.time() - 7200,))
    assert cache.get("details", "job", 3600) is None
    with sqlite3.connect(cache.path) as connection:
        connection.execute("UPDATE entries SET updated=?, value='{'", (time.time(),))
    assert cache.get("details", "job", 3600) is None


def test_corrupt_cache_does_not_prevent_fresh_work(cache):
    cache.path.write_bytes(b"not a database")
    assert cache.get("analysis", "job", 3600) is None
    cache.put("analysis", "job", {"reason": "Example"})


def test_overlapping_runs_are_rejected_and_the_lock_is_released(cache):
    with discovery_lock():
        with pytest.raises(RuntimeError, match="Another discovery"):
            with discovery_lock():
                pytest.fail("Overlapping discovery was allowed")
    with discovery_lock():
        pass


@pytest.fixture
def analysis(cache, monkeypatch):
    profile = {"skills": ["Python", "SQL"]}
    monkeypatch.setattr(scorer, "load_resume_profile", lambda: profile)
    monkeypatch.setattr(
        scorer, "load_candidate_profile", lambda: {"preferred_locations": ["Remote"]}
    )
    generate = MagicMock(
        return_value={"matched_skills": ["Python"], "missing_skills": [], "reason": "Good fit."}
    )
    monkeypatch.setattr(scorer, "generate_json", generate)
    monkeypatch.setattr(
        scorer, "validate_response", lambda response, job: {"score": 80, "status": "Apply"}
    )
    job = {
        "title": "Engineer",
        "company": "Acme",
        "location": "Remote",
        "description": "Unique description marker: Python pipelines.",
        "raw": {"description": "Unique description marker: Python pipelines.", "fetched_at": "old"},
    }
    return job, profile, generate


def test_prompt_excludes_duplicate_description_and_raw_metadata(analysis):
    job, _, _ = analysis
    prompt = scorer.build_prompt(job)
    assert prompt.count("Unique description marker") == 1
    assert "fetched_at" not in prompt
    assert '"skills":["Python","SQL"]' in prompt


def test_repeated_job_reuses_analysis_but_recomputes_score(analysis, monkeypatch):
    job, _, generate = analysis
    assert scorer.score_job(job)["score"] == 80
    job["raw"]["fetched_at"] = "new"
    monkeypatch.setattr(
        scorer, "validate_response", lambda response, job: {"score": 90, "status": "Apply"}
    )
    assert scorer.score_job(job)["score"] == 90
    assert generate.call_count == 1


@pytest.mark.parametrize("changed", ["description", "profile", "model", "prompt", "options"])
def test_analysis_is_invalidated_when_its_inputs_change(analysis, monkeypatch, changed):
    job, profile, generate = analysis
    scorer.score_job(job)
    if changed == "description":
        job["description"] += " Kafka required."
    elif changed == "profile":
        profile["skills"].append("Kafka")
    elif changed == "model":
        monkeypatch.setattr(scorer, "OLLAMA_MODEL", "different-model")
    elif changed == "prompt":
        monkeypatch.setattr(
            scorer, "SCORING_PROMPT", scorer.SCORING_PROMPT + "Changed instructions"
        )
    else:
        monkeypatch.setattr(scorer, "OLLAMA_OPTIONS", {"temperature": 0.1})
    scorer.score_job(job)
    assert generate.call_count == 2


def test_incomplete_model_answers_are_not_cached(analysis):
    job, _, generate = analysis
    generate.return_value = {"matched_skills": "wrong", "missing_skills": [], "reason": ""}
    for _ in range(2):
        with pytest.raises(ValueError, match="incomplete"):
            scorer.score_job(job)
    assert generate.call_count == 2


@pytest.fixture
def pipeline(tmp_path, monkeypatch, cache):
    monkeypatch.setattr(discovery, "JOB_RESULTS_JSON", tmp_path / "job_results.json")
    monkeypatch.setattr(discovery, "JOB_RESULTS_CSV", tmp_path / "job_results.csv")
    monkeypatch.setattr(discovery, "update_job_history", MagicMock())
    registry = MagicMock()
    registry.discover.return_value = registry
    monkeypatch.setattr(discovery, "SourceRegistry", lambda: registry)
    manager = MagicMock(last_errors={})
    monkeypatch.setattr(discovery, "SourceManager", lambda _: manager)
    engine = MagicMock()
    monkeypatch.setattr(discovery, "DiscoveryEngine", lambda _: engine)
    score = MagicMock(return_value={"score": 80, "status": "Apply", "reason": "Good fit."})
    monkeypatch.setattr(discovery, "score_job", score)
    return engine, score


def test_completed_job_is_saved_before_the_next_job_is_read(pipeline):
    engine, score = pipeline
    job = Job(title="Engineer", url="https://example.com/new")
    discovery.JOB_RESULTS_JSON.write_text('[{"url":"https://example.com/previous"}]')

    def interrupted(**kwargs):
        kwargs["on_job"](job)
        saved = json.loads(discovery.JOB_RESULTS_JSON.read_text())
        assert {row["url"] for row in saved} == {job.url, "https://example.com/previous"}
        raise KeyboardInterrupt()

    engine.discover.side_effect = interrupted
    with pytest.raises(KeyboardInterrupt):
        discovery.run_discovery()
    assert len(json.loads(discovery.JOB_RESULTS_JSON.read_text())) == 2
    assert score.call_count == 1


def test_callback_and_returned_list_do_not_score_the_job_twice(pipeline):
    engine, score = pipeline
    job = Job(title="Engineer", url="https://example.com/new")

    def discover(**kwargs):
        kwargs["on_job"](job)
        return [job]

    engine.discover.side_effect = discover
    assert len(discovery.run_discovery()) == 1
    assert score.call_count == 1


def test_one_scoring_failure_does_not_discard_other_jobs(pipeline):
    engine, score = pipeline
    engine.discover.return_value = [
        Job(url="https://example.com/one"),
        Job(url="https://example.com/two"),
    ]
    score.side_effect = [
        RuntimeError("Model failed"),
        {"score": 80, "status": "Apply", "reason": "Fit"},
    ]
    results = discovery.run_discovery()
    assert [row["url"] for row in results] == ["https://example.com/two"]


def test_failed_export_replacement_preserves_the_original(tmp_path, monkeypatch):
    target = tmp_path / "result.json"
    target.write_text("original")
    monkeypatch.setattr(
        "core.persistence.os.replace", MagicMock(side_effect=OSError("Interrupted"))
    )
    with pytest.raises(OSError):
        write_text_atomic(target, "replacement")
    assert target.read_text() == "original"
    assert list(tmp_path.glob("*.tmp")) == []
