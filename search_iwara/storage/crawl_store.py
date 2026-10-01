"""Write side of the storage layer: everything the sync pipeline persists."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self

from ..models import CrawlerStats, EntityKind, EntityRef, ListUpsertResult, MovieDetail, MovieListItem
from ..utils import ASCII_DIGITS_RE, utc_now
from .connection import TransactionManager, connect
from .migrations import migrate
from .search_index import index_movie
from .sql import ENTITY_STATS_REFRESH, ENTITY_TABLES, HOT_SCORE_UPDATE, HOT_SCORE_UPDATE_RECENT

RETRY_BASE = timedelta(minutes=30)
RUN_COUNTERS = (
    "pages_checked",
    "failed_pages",
    "movies_seen",
    "new_movies",
    "changed_movies",
    "details_fetched",
    "missing_movies",
    "failed_details",
)
RETRY_CAP = timedelta(days=7)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat()


class CrawlStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.conn = connection
        self._tx = TransactionManager(connection)

    @classmethod
    def open(cls, db_path: Path) -> Self:
        connection = connect(db_path)
        migrate(connection)
        return cls(connection)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._tx.transaction():
            yield

    # --- entities & relations ----------------------------------------------------------------

    def _upsert_entity(self, kind: EntityKind, entity: EntityRef) -> int:
        table = ENTITY_TABLES[kind][0]
        now = utc_now()
        row = self.conn.execute(
            f"""
            INSERT INTO {table} (source_site_id, name, oreno3d_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_site_id) DO UPDATE SET
                name = excluded.name,
                oreno3d_url = COALESCE(excluded.oreno3d_url, {table}.oreno3d_url),
                updated_at = excluded.updated_at
            RETURNING id
            """,
            (entity.source_id, entity.name, entity.url, now, now),
        ).fetchone()
        return int(row["id"])

    def _replace_relations(self, movie_id: int, kind: EntityKind, entity_ids: list[int]) -> None:
        _, join_table, column = ENTITY_TABLES[kind]
        self.conn.execute(f"DELETE FROM {join_table} WHERE movie_id = ?", (movie_id,))
        self.conn.executemany(
            f"INSERT OR IGNORE INTO {join_table} (movie_id, {column}) VALUES (?, ?)",
            [(movie_id, entity_id) for entity_id in entity_ids],
        )

    def _reindex_search(self, movie_id: int) -> None:
        index_movie(self.conn, movie_id)

    # --- movies ------------------------------------------------------------------------------

    def upsert_movie_list_item(self, item: MovieListItem) -> ListUpsertResult:
        now = utc_now()
        row = self.conn.execute(
            """
            SELECT id, title, author_display_name, thumbnail_url, view_count, favorite_count,
                   detail_fetched_at, status
            FROM movies WHERE source_site_id = ?
            """,
            (item.source_site_id,),
        ).fetchone()

        if row is None:
            inserted = self.conn.execute(
                """
                INSERT INTO movies (
                    source_site_id, oreno3d_url, title, author_display_name, thumbnail_url,
                    view_count, favorite_count, status, list_seen_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                RETURNING id
                """,
                (
                    item.source_site_id,
                    item.oreno3d_url,
                    item.title,
                    item.author_name,
                    item.thumbnail_url,
                    item.view_count,
                    item.favorite_count,
                    now,
                    now,
                    now,
                ),
            ).fetchone()
            movie_id = int(inserted["id"])
            self._reindex_search(movie_id)
            return ListUpsertResult(movie_id=movie_id, is_new=True, list_changed=True, needs_detail=True)

        movie_id = int(row["id"])
        title_changed = row["title"] != item.title or row["author_display_name"] != item.author_name
        list_changed = (
            title_changed
            or row["status"] != "active"
            or row["thumbnail_url"] != item.thumbnail_url
            or row["view_count"] != item.view_count
            or row["favorite_count"] != item.favorite_count
        )
        self.conn.execute(
            """
            UPDATE movies
            SET oreno3d_url = ?, title = ?, author_display_name = ?,
                thumbnail_url = COALESCE(?, thumbnail_url),
                view_count = ?, favorite_count = ?, list_seen_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                item.oreno3d_url,
                item.title,
                item.author_name,
                item.thumbnail_url,
                item.view_count,
                item.favorite_count,
                now,
                now,
                movie_id,
            ),
        )
        if title_changed:
            self._reindex_search(movie_id)
        return ListUpsertResult(
            movie_id=movie_id,
            is_new=False,
            list_changed=list_changed,
            needs_detail=row["detail_fetched_at"] is None or row["status"] != "active",
        )

    def apply_movie_detail(self, detail: MovieDetail) -> None:
        now = utc_now()
        author_id = self._upsert_entity("authors", detail.author) if detail.author else None
        values = (
            detail.oreno3d_url,
            detail.external_video_url,
            detail.title,
            author_id,
            detail.author.name if detail.author else None,
            detail.thumbnail_url,
            detail.published_at,
            detail.view_count,
            detail.favorite_count,
            detail.author_comment,
            now,
            now,
        )
        row = self.conn.execute(
            """
            INSERT INTO movies (
                oreno3d_url, external_video_url, title, author_id, author_display_name, thumbnail_url,
                published_at, view_count, favorite_count, author_comment, detail_fetched_at, updated_at,
                source_site_id, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(source_site_id) DO UPDATE SET
                oreno3d_url = excluded.oreno3d_url,
                external_video_url = excluded.external_video_url,
                title = excluded.title,
                author_id = excluded.author_id,
                author_display_name = excluded.author_display_name,
                thumbnail_url = COALESCE(excluded.thumbnail_url, movies.thumbnail_url),
                published_at = excluded.published_at,
                view_count = excluded.view_count,
                favorite_count = excluded.favorite_count,
                author_comment = excluded.author_comment,
                detail_fetched_at = excluded.detail_fetched_at,
                status = 'active',
                updated_at = excluded.updated_at
            RETURNING id
            """,
            (*values, detail.source_site_id, now),
        ).fetchone()
        movie_id = int(row["id"])
        relations: tuple[tuple[EntityKind, list[EntityRef]], ...] = (
            ("tags", detail.tags),
            ("origins", detail.origins),
            ("characters", detail.characters),
        )
        for kind, entities in relations:
            ids = [self._upsert_entity(kind, entity) for entity in entities]
            self._replace_relations(movie_id, kind, ids)
        self._reindex_search(movie_id)

    def mark_movie_missing(self, source_site_id: int, oreno3d_url: str) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO movies (
                source_site_id, oreno3d_url, status, detail_fetched_at, created_at, updated_at
            )
            VALUES (?, ?, 'missing', ?, ?, ?)
            ON CONFLICT(source_site_id) DO UPDATE SET
                oreno3d_url = excluded.oreno3d_url,
                status = 'missing',
                detail_fetched_at = excluded.detail_fetched_at,
                updated_at = excluded.updated_at
            """,
            (source_site_id, oreno3d_url, now, now, now),
        )

    # --- crawl bookkeeping -------------------------------------------------------------------

    def log_error(
        self,
        *,
        entity_type: str,
        entity_id: str,
        operation: str,
        url: str,
        error: BaseException,
        now: datetime | None = None,
    ) -> int:
        """Record a failure and schedule its next retry (exponential, capped). Returns attempts."""

        moment = now or datetime.now(UTC)
        row = self.conn.execute(
            "SELECT attempts FROM crawl_errors WHERE entity_type = ? AND entity_id = ? AND operation = ?",
            (entity_type, entity_id, operation),
        ).fetchone()
        attempts = 1 if row is None else int(row["attempts"]) + 1
        next_retry = moment + min(RETRY_CAP, RETRY_BASE * (2 ** (attempts - 1)))
        self.conn.execute(
            """
            INSERT INTO crawl_errors (
                entity_type, entity_id, operation, url, error_type, error_message, attempts,
                last_failed_at, next_retry_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_type, entity_id, operation) DO UPDATE SET
                url = excluded.url,
                error_type = excluded.error_type,
                error_message = excluded.error_message,
                attempts = excluded.attempts,
                last_failed_at = excluded.last_failed_at,
                next_retry_at = excluded.next_retry_at
            """,
            (
                entity_type,
                entity_id,
                operation,
                url,
                type(error).__name__,
                str(error)[:2000],
                attempts,
                _iso(moment),
                _iso(next_retry),
            ),
        )
        return attempts

    def clear_error(self, *, entity_type: str, entity_id: str, operation: str) -> None:
        self.conn.execute(
            "DELETE FROM crawl_errors WHERE entity_type = ? AND entity_id = ? AND operation = ?",
            (entity_type, entity_id, operation),
        )

    def set_state(self, key: str, value: str | int) -> None:
        self.conn.execute(
            """
            INSERT INTO crawl_state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, str(value), utc_now()),
        )

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM crawl_state WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def any_listed_since(self, source_ids: list[int], since: str) -> bool:
        """True if any of these movies was seen on a listing page at or after ``since``."""

        if not source_ids:
            return False
        placeholders = ", ".join("?" * len(source_ids))
        row = self.conn.execute(
            f"SELECT 1 FROM movies WHERE source_site_id IN ({placeholders}) AND list_seen_at >= ? LIMIT 1",
            (*source_ids, since),
        ).fetchone()
        return row is not None

    def get_state_int(self, key: str, default: int = 0) -> int:
        row = self.conn.execute("SELECT value FROM crawl_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return int(row["value"])
        except ValueError:
            return default

    def retryable_failed_movie_ids(self, *, max_attempts: int, now: datetime | None = None) -> list[int]:
        """Movies whose detail fetch failed, are due for a retry and haven't hit the cap."""

        rows = self.conn.execute(
            """
            SELECT entity_id FROM crawl_errors
            WHERE entity_type = 'movie' AND operation = 'detail'
              AND attempts < ? AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY last_failed_at DESC
            """,
            (max_attempts, _iso(now or datetime.now(UTC))),
        ).fetchall()
        return [int(row["entity_id"]) for row in rows if ASCII_DIGITS_RE.fullmatch(str(row["entity_id"]))]

    def movies_missing_detail(self) -> list[int]:
        rows = self.conn.execute(
            """
            SELECT source_site_id FROM movies
            WHERE status = 'active' AND detail_fetched_at IS NULL
            ORDER BY source_site_id DESC
            """
        ).fetchall()
        return [int(row["source_site_id"]) for row in rows]

    def stale_detail_ids(
        self, *, window_days: int, refresh_after_hours: int, limit: int, now: datetime | None = None
    ) -> list[int]:
        """Recently published movies whose details (tags, counts…) are older than the TTL."""

        if limit <= 0 or window_days <= 0:
            return []
        moment = now or datetime.now(UTC)
        rows = self.conn.execute(
            """
            SELECT source_site_id FROM movies
            WHERE status = 'active'
              AND detail_fetched_at IS NOT NULL AND detail_fetched_at < ?
              AND published_at >= ?
            ORDER BY detail_fetched_at ASC
            LIMIT ?
            """,
            (
                _iso(moment - timedelta(hours=refresh_after_hours)),
                (moment - timedelta(days=window_days)).strftime("%Y-%m-%d"),
                limit,
            ),
        ).fetchall()
        return [int(row["source_site_id"]) for row in rows]

    # --- derived data & run history ----------------------------------------------------------

    def refresh_derived(self, *, full: bool = True) -> None:
        """Recompute time-decayed scores and, when ``full``, the ranking read model.

        A run that changed nothing only refreshes recent hot scores (older ones barely move).
        """

        with self.transaction():
            if full:
                self.conn.execute(HOT_SCORE_UPDATE)
                for statement in ENTITY_STATS_REFRESH:
                    self.conn.execute(statement)
            else:
                self.conn.execute(HOT_SCORE_UPDATE_RECENT)
            self.conn.execute(
                "INSERT INTO app_meta(key, value) VALUES ('derived_refreshed_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (utc_now(),),
            )
        self.conn.execute("PRAGMA optimize")

    def start_run(self, mode: str) -> int:
        """Open a run record. Called under the sync lock, so any other 'running' row is orphaned."""

        now = utc_now()
        with self.transaction():
            self.conn.execute(
                "UPDATE sync_runs SET status = 'failed', finished_at = ?, "
                "error = COALESCE(error, 'abandoned: the process exited without finishing') "
                "WHERE status = 'running'",
                (now,),
            )
            row = self.conn.execute(
                "INSERT INTO sync_runs (mode, status, started_at) VALUES (?, 'running', ?) RETURNING id",
                (mode, now),
            ).fetchone()
        return int(row["id"])

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        counters: dict[str, int],
        error: str | None = None,
        crawler: CrawlerStats | None = None,
    ) -> None:
        values: dict[str, object] = {name: counters[name] for name in RUN_COUNTERS if name in counters}
        if crawler is not None:
            values |= {
                "requests": crawler.requests,
                "retries": crawler.retries,
                "throttled": crawler.throttled,
                "status_codes": json.dumps(dict(sorted(crawler.status_codes.items()))),
            }
        assignments = "".join(f", {name} = ?" for name in values)
        with self.transaction():
            self.conn.execute(
                f"UPDATE sync_runs SET status = ?, finished_at = ?, error = ?{assignments} WHERE id = ?",
                (status, utc_now(), error, *values.values(), run_id),
            )
