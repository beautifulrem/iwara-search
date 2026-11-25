"""SQLite connection factory, transactions and a per-thread read-only pool for the web tier."""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

SQLITE_TRIGRAM_MIN_VERSION = (3, 34, 0)
SQLITE_CONTENTLESS_DELETE_MIN_VERSION = (3, 43, 0)
WAL_JOURNAL_SIZE_LIMIT_BYTES = 64 * 1024 * 1024
_GIB = 1024 * 1024 * 1024
_MIB = 1024 * 1024


class StorageError(RuntimeError):
    pass


def trigram_supported() -> bool:
    return sqlite3.sqlite_version_info >= SQLITE_TRIGRAM_MIN_VERSION


def contentless_delete_supported() -> bool:
    return sqlite3.sqlite_version_info >= SQLITE_CONTENTLESS_DELETE_MIN_VERSION


def _detected_memory_limit_bytes(cgroup_max_path: Path = Path("/sys/fs/cgroup/memory.max")) -> int | None:
    candidates: list[int] = []
    with suppress(OSError, ValueError):
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            candidates.append(pages * page_size)
    with suppress(OSError, ValueError):
        raw = cgroup_max_path.read_text(encoding="utf-8").strip()
        if raw.isdecimal():
            limit = int(raw)
            if limit > 0:
                candidates.append(limit)
    return min(candidates) if candidates else None


def default_mmap_bytes(
    *,
    env_override: str | None = None,
    cgroup_max_path: Path = Path("/sys/fs/cgroup/memory.max"),
) -> int:
    """Scale SQLite's ``mmap_size`` to available RAM so small cgroups do not thrash."""

    raw_override = os.environ.get("SEARCH_IWARA_SQLITE_MMAP_BYTES") if env_override is None else env_override
    if raw_override is not None and raw_override.strip():
        value = raw_override.strip()
        if value.isdecimal():
            return min(int(value), 1024 * _MIB)
    limit = _detected_memory_limit_bytes(cgroup_max_path)
    if limit is not None and limit < int(1.5 * _GIB):
        return 32 * _MIB
    if limit is not None and limit < 3 * _GIB:
        return 64 * _MIB
    return 256 * _MIB


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
    connection.execute(f"PRAGMA mmap_size = {default_mmap_bytes()}")
    if readonly:
        connection.execute("PRAGMA query_only = ON")
    else:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute(f"PRAGMA journal_size_limit = {WAL_JOURNAL_SIZE_LIMIT_BYTES}")
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
        try:
            st = self.db_path.stat()
        except OSError as exc:
            raise StorageError(f"database {self.db_path} is unavailable: {exc}") from exc
        current_inode = (st.st_dev, st.st_ino)
        connection: sqlite3.Connection | None = getattr(self._local, "connection", None)
        cached_inode: tuple[int, int] | None = getattr(self._local, "inode", None)
        if connection is not None and cached_inode != current_inode:
            with self._lock:
                if connection in self._all:
                    self._all.remove(connection)
            connection.close()
            connection = None
        if connection is None:
            connection = connect(self.db_path, readonly=True)
            self._local.connection = connection
            self._local.inode = current_inode
            with self._lock:
                self._all.append(connection)
        return connection

    def close(self) -> None:
        with self._lock:
            for connection in self._all:
                connection.close()
            self._all.clear()
        self._local = threading.local()
