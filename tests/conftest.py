"""Regression tests must never read or replace a user's discovery cache."""

import pytest

import discovery_cache


@pytest.fixture(autouse=True)
def isolated_discovery_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery_cache, "CACHE_PATH", tmp_path / "discovery_cache.sqlite3")
