"""Local, expiring checkpoints for descriptions and semantic analysis."""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from config import PROJECT_DIR

CACHE_PATH = PROJECT_DIR / "discovery_cache.sqlite3"


@contextmanager
def discovery_lock():
    """Reject overlapping runs; the OS releases the lock after a crash."""
    with Path(str(CACHE_PATH) + ".lock").open("a+b") as file:
        if file.tell() == 0:
            file.write(b"0")
            file.flush()
        file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError(
                "Another discovery run is active. Wait for it or cancel it before retrying."
            ) from error
        try:
            yield
        finally:
            file.seek(0)
            if os.name == "nt":
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


class DiscoveryCache:
    def __init__(self, path: Path | None = None):
        self.path = path or CACHE_PATH

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS entries (namespace TEXT, key TEXT, "
                    "updated REAL, value TEXT, PRIMARY KEY(namespace, key))"
                )
                yield connection
        finally:
            connection.close()

    def get(self, namespace: str, key: str, max_age_s: float) -> dict | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT updated, value FROM entries WHERE namespace=? AND key=?",
                    (namespace, key),
                ).fetchone()
            if row and 0 <= time.time() - row[0] <= max_age_s:
                value = json.loads(row[1])
                return value if isinstance(value, dict) else None
        except (OSError, sqlite3.Error, ValueError):
            pass  # Cache failures must not prevent a fresh search or score.
        return None

    def put(self, namespace: str, key: str, value: dict) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?)",
                    (namespace, key, time.time(), json.dumps(value)),
                )
        except (OSError, sqlite3.Error, TypeError):
            pass
