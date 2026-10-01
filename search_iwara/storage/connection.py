"""SQLite connection factory, transactions and a per-thread read-only pool for the web tier."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SQLITE_TRIGRAM_MIN_VERSION = (3, 34, 0)


class StorageError(RuntimeError):
    pass


def trigram_supported() -> bool:
    return sqlite3.sqlite_version_info >= SQLITE_TRIGRAM_MIN_VERSION


def connect(db_path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Open a tuned connection in autocommit mode (transactions are explicit, see below)."""

    if not readonly:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    elif not db_path.exists():
        raise StorageError(f"database {db_path} does not exist; run `search-iwara db migrate` first")
    connection = sqlite3.connect(db_path, timeout=10.0, isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA temp_store = MEMORY")
    # Page cache per connection: 32 MB for the writer, 8 MB for each read-only web thread
    # (the pages themselves are shared through mmap, so small per-thread caches suffice).
    connection.execute(f"PRAGMA cache_size = {-8000 if readonly else -32000}")
    connection.execute("PRAGMA mmap_size = 268435456")
    if readonly:
        connection.execute("PRAGMA query_only = ON")
    else:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    return connection


class TransactionManager:
    """Re-entrant ``BEGIN IMMEDIATE … COMMIT`` wrapper: only the outermost block commits."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.conn = connection
        self._depth = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")
        finally:
            self._depth = 0


class ReadOnlyPool:
    """One read-only connection per worker thread.

    FastAPI runs sync endpoints in a thread pool; SQLite connections must not be used by two
    threads at once, so each thread lazily gets its own connection, reused across requests.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

    def get(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if connection is None:
            connection = connect(self.db_path, readonly=True)
            self._local.connection = connection
            with self._lock:
                self._all.append(connection)
        return connection

    def close(self) -> None:
        with self._lock:
            for connection in self._all:
                connection.close()
            self._all.clear()
        self._local = threading.local()
