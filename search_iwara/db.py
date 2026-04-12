from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from .config import get_settings
from .models import EntityRef, ListUpsertResult, MovieDetail, MovieListItem, SearchFilters
from .utils import escape_like, format_number, fts_query_from_text, page_count, split_query_tokens, utc_now


EntityKind = Literal["authors", "tags", "origins", "characters"]


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_site_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    oreno3d_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_site_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    oreno3d_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS origins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_site_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    oreno3d_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_site_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    oreno3d_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_site_id INTEGER NOT NULL UNIQUE,
    oreno3d_url TEXT NOT NULL,
    external_video_url TEXT,
    title TEXT NOT NULL DEFAULT '',
    author_id INTEGER REFERENCES authors(id) ON DELETE SET NULL,
    author_display_name TEXT,
    thumbnail_url TEXT,
    published_at TEXT,
    view_count INTEGER,
    favorite_count INTEGER,
    author_comment TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    list_seen_at TEXT,
    detail_fetched_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movie_tags (
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (movie_id, tag_id)
);

CREATE TABLE IF NOT EXISTS movie_origins (
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    origin_id INTEGER NOT NULL REFERENCES origins(id) ON DELETE CASCADE,
    PRIMARY KEY (movie_id, origin_id)
);

CREATE TABLE IF NOT EXISTS movie_characters (
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    PRIMARY KEY (movie_id, character_id)
);

CREATE TABLE IF NOT EXISTS crawl_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crawl_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    url TEXT NOT NULL,
    error_message TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    last_failed_at TEXT NOT NULL,
    UNIQUE(entity_type, entity_id, operation)
);

CREATE VIRTUAL TABLE IF NOT EXISTS movie_fts USING fts5(
    title,
    content='movies',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS movies_ai AFTER INSERT ON movies BEGIN
    INSERT INTO movie_fts(rowid, title) VALUES (new.id, new.title);
END;

CREATE TRIGGER IF NOT EXISTS movies_ad AFTER DELETE ON movies BEGIN
    INSERT INTO movie_fts(movie_fts, rowid, title) VALUES ('delete', old.id, old.title);
END;

CREATE TRIGGER IF NOT EXISTS movies_au AFTER UPDATE ON movies BEGIN
    INSERT INTO movie_fts(movie_fts, rowid, title) VALUES ('delete', old.id, old.title);
    INSERT INTO movie_fts(rowid, title) VALUES (new.id, new.title);
END;

CREATE INDEX IF NOT EXISTS idx_movies_source_site_id ON movies(source_site_id);
CREATE INDEX IF NOT EXISTS idx_movies_status ON movies(status);
CREATE INDEX IF NOT EXISTS idx_movies_published_at ON movies(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_movies_favorite_count ON movies(favorite_count DESC);
CREATE INDEX IF NOT EXISTS idx_movies_view_count ON movies(view_count DESC);
CREATE INDEX IF NOT EXISTS idx_movies_author_id ON movies(author_id);
CREATE INDEX IF NOT EXISTS idx_tags_source_site_id ON tags(source_site_id);
CREATE INDEX IF NOT EXISTS idx_authors_source_site_id ON authors(source_site_id);
CREATE INDEX IF NOT EXISTS idx_origins_source_site_id ON origins(source_site_id);
CREATE INDEX IF NOT EXISTS idx_characters_source_site_id ON characters(source_site_id);
CREATE INDEX IF NOT EXISTS idx_crawl_errors_lookup ON crawl_errors(entity_type, entity_id, operation);
"""


ENTITY_TABLES: dict[EntityKind, tuple[str, str]] = {
    "authors": ("authors", "author_id"),
    "tags": ("tags", "tag_id"),
    "origins": ("origins", "origin_id"),
    "characters": ("characters", "character_id"),
}

POPULARITY_SCORE_SQL = "(COALESCE(m.view_count, 0) + COALESCE(m.favorite_count, 0) * 50)"
HOT_SCORE_SQL = (
    f"(({POPULARITY_SCORE_SQL}) / "
    "(MAX(((julianday('now') - julianday(COALESCE(m.published_at, '1970-01-01 00:00'))) * 24.0), 0.0) + 6.0))"
)


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    settings = get_settings(db_path)
    # FastAPI may open and close a request-scoped repository in different worker threads.
    connection = sqlite3.connect(str(settings.db_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.executescript(SCHEMA_SQL)
    return connection


class Repository:
    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection

    @classmethod
    def open(cls, db_path: str | Path | None = None) -> "Repository":
        return cls(connect(db_path))

    def close(self) -> None:
        self.conn.close()

    def save(self) -> None:
        self.conn.commit()

    @contextmanager
    def transaction(self):
        try:
            yield
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def _entity_table(self, kind: EntityKind) -> tuple[str, str]:
        return ENTITY_TABLES[kind]

    def _upsert_entity(self, kind: EntityKind, entity: EntityRef) -> int:
        table, _ = self._entity_table(kind)
        now = utc_now()
        self.conn.execute(
            f"""
            INSERT INTO {table} (source_site_id, name, oreno3d_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_site_id) DO UPDATE SET
                name = excluded.name,
                oreno3d_url = COALESCE(excluded.oreno3d_url, {table}.oreno3d_url),
                updated_at = excluded.updated_at
            """,
            (entity.source_id, entity.name, entity.url, now, now),
        )
        row = self.conn.execute(
            f"SELECT id FROM {table} WHERE source_site_id = ?",
            (entity.source_id,),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def _replace_movie_relations(
        self,
        movie_id: int,
        join_table: str,
        join_column: str,
        entity_ids: list[int],
    ) -> None:
        self.conn.execute(f"DELETE FROM {join_table} WHERE movie_id = ?", (movie_id,))
        for entity_id in entity_ids:
            self.conn.execute(
                f"INSERT OR IGNORE INTO {join_table} (movie_id, {join_column}) VALUES (?, ?)",
                (movie_id, entity_id),
            )

    def upsert_movie_list_item(self, item: MovieListItem) -> ListUpsertResult:
        now = utc_now()
        row = self.conn.execute(
            """
            SELECT id, title, author_display_name, thumbnail_url, view_count, favorite_count,
                   detail_fetched_at, status
            FROM movies
            WHERE source_site_id = ?
            """,
            (item.source_site_id,),
        ).fetchone()

        if row is None:
            cursor = self.conn.execute(
                """
                INSERT INTO movies (
                    source_site_id, oreno3d_url, title, author_display_name, thumbnail_url,
                    view_count, favorite_count, status, list_seen_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
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
            )
            return ListUpsertResult(
                movie_id=int(cursor.lastrowid),
                is_new=True,
                list_changed=True,
                needs_detail=True,
            )

        comparisons = {
            "title": item.title,
            "author_display_name": item.author_name,
            "thumbnail_url": item.thumbnail_url,
            "view_count": item.view_count,
            "favorite_count": item.favorite_count,
        }
        list_changed = row["status"] != "active"
        for key, value in comparisons.items():
            if row[key] != value:
                list_changed = True
                break

        self.conn.execute(
            """
            UPDATE movies
            SET oreno3d_url = ?,
                title = ?,
                author_display_name = ?,
                thumbnail_url = ?,
                view_count = ?,
                favorite_count = ?,
                status = 'active',
                list_seen_at = ?,
                updated_at = ?
            WHERE source_site_id = ?
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
                item.source_site_id,
            ),
        )
        return ListUpsertResult(
            movie_id=int(row["id"]),
            is_new=False,
            list_changed=list_changed,
            needs_detail=row["detail_fetched_at"] is None or row["status"] != "active",
        )

    def apply_movie_detail(self, detail: MovieDetail) -> None:
        now = utc_now()
        author_id = self._upsert_entity("authors", detail.author) if detail.author else None
        tag_ids = [self._upsert_entity("tags", tag) for tag in detail.tags]
        origin_ids = [self._upsert_entity("origins", origin) for origin in detail.origins]
        character_ids = [self._upsert_entity("characters", char) for char in detail.characters]

        row = self.conn.execute(
            "SELECT id FROM movies WHERE source_site_id = ?",
            (detail.source_site_id,),
        ).fetchone()

        if row is None:
            cursor = self.conn.execute(
                """
                INSERT INTO movies (
                    source_site_id, oreno3d_url, external_video_url, title, author_id,
                    author_display_name, thumbnail_url, published_at, view_count,
                    favorite_count, author_comment, detail_fetched_at, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    detail.source_site_id,
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
                    now,
                ),
            )
            movie_id = int(cursor.lastrowid)
        else:
            movie_id = int(row["id"])
            self.conn.execute(
                """
                UPDATE movies
                SET oreno3d_url = ?,
                    external_video_url = ?,
                    title = ?,
                    author_id = ?,
                    author_display_name = ?,
                    thumbnail_url = COALESCE(?, thumbnail_url),
                    published_at = ?,
                    view_count = ?,
                    favorite_count = ?,
                    author_comment = ?,
                    detail_fetched_at = ?,
                    status = 'active',
                    updated_at = ?
                WHERE source_site_id = ?
                """,
                (
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
                    detail.source_site_id,
                ),
            )

        self._replace_movie_relations(movie_id, "movie_tags", "tag_id", tag_ids)
        self._replace_movie_relations(movie_id, "movie_origins", "origin_id", origin_ids)
        self._replace_movie_relations(movie_id, "movie_characters", "character_id", character_ids)

    def mark_movie_missing(self, source_site_id: int, oreno3d_url: str) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO movies (source_site_id, oreno3d_url, status, detail_fetched_at, created_at, updated_at)
            VALUES (?, ?, 'missing', ?, ?, ?)
            ON CONFLICT(source_site_id) DO UPDATE SET
                oreno3d_url = excluded.oreno3d_url,
                status = 'missing',
                detail_fetched_at = excluded.detail_fetched_at,
                updated_at = excluded.updated_at
            """,
            (source_site_id, oreno3d_url, now, now, now),
        )

    def log_error(
        self,
        *,
        entity_type: str,
        entity_id: str,
        operation: str,
        url: str,
        error_message: str,
    ) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO crawl_errors (entity_type, entity_id, operation, url, error_message, attempts, last_failed_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(entity_type, entity_id, operation) DO UPDATE SET
                url = excluded.url,
                error_message = excluded.error_message,
                attempts = crawl_errors.attempts + 1,
                last_failed_at = excluded.last_failed_at
            """,
            (entity_type, entity_id, operation, url, error_message, now),
        )

    def clear_error(self, *, entity_type: str, entity_id: str, operation: str) -> None:
        self.conn.execute(
            """
            DELETE FROM crawl_errors
            WHERE entity_type = ? AND entity_id = ? AND operation = ?
            """,
            (entity_type, entity_id, operation),
        )

    def set_state(self, key: str, value: str | int) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO crawl_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, str(value), now),
        )

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM crawl_state WHERE key = ?",
            (key,),
        ).fetchone()
        return None if row is None else str(row["value"])

    def get_state_int(self, key: str, default: int = 0) -> int:
        value = self.get_state(key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return default

    def get_movies_needing_detail(self, *, limit: int | None = None) -> list[int]:
        sql = """
            SELECT DISTINCT m.source_site_id
            FROM movies m
            LEFT JOIN crawl_errors e
                ON e.entity_type = 'movie'
               AND e.operation = 'detail'
               AND e.entity_id = CAST(m.source_site_id AS TEXT)
            WHERE m.status = 'active'
              AND (m.detail_fetched_at IS NULL OR e.id IS NOT NULL)
            ORDER BY m.source_site_id DESC
        """
        params: list[Any] = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [int(row["source_site_id"]) for row in rows]

    def get_failed_movie_ids(self) -> list[int]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT entity_id
            FROM crawl_errors
            WHERE entity_type = 'movie' AND operation = 'detail'
            ORDER BY last_failed_at DESC
            """
        ).fetchall()
        result: list[int] = []
        for row in rows:
            try:
                result.append(int(row["entity_id"]))
            except ValueError:
                continue
        return result

    def autocomplete_entities(self, kind: EntityKind, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        table, _ = self._entity_table(kind)
        cleaned = query.strip()
        if cleaned:
            like = f"%{cleaned}%"
            rows = self.conn.execute(
                f"""
                SELECT source_site_id AS id, name
                FROM {table}
                WHERE name LIKE ? COLLATE NOCASE
                ORDER BY INSTR(LOWER(name), LOWER(?)), name
                LIMIT ?
                """,
                (like, cleaned, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"""
                SELECT source_site_id AS id, name
                FROM {table}
                ORDER BY name
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{"id": int(row["id"]), "name": str(row["name"])} for row in rows]

    def resolve_entities(self, kind: EntityKind, source_ids: list[int]) -> list[dict[str, Any]]:
        if not source_ids:
            return []
        table, _ = self._entity_table(kind)
        placeholders = ", ".join("?" for _ in source_ids)
        rows = self.conn.execute(
            f"""
            SELECT source_site_id AS id, name
            FROM {table}
            WHERE source_site_id IN ({placeholders})
            """,
            source_ids,
        ).fetchall()
        lookup = {int(row["id"]): {"id": int(row["id"]), "name": str(row["name"])} for row in rows}
        return [lookup[item] for item in source_ids if item in lookup]

    def _build_search_where(self, filters: SearchFilters) -> tuple[str, list[Any]]:
        clauses = ["m.status = 'active'"]
        params: list[Any] = []

        title_clauses: list[str] = []
        fts_query = fts_query_from_text(filters.q, filters.title_mode)
        if fts_query:
            title_clauses.append("m.id IN (SELECT rowid FROM movie_fts WHERE movie_fts MATCH ?)")
            params.append(fts_query)

        title_tokens = split_query_tokens(filters.q)
        if title_tokens:
            joiner = " OR " if filters.title_mode == "any" else " AND "
            like_clauses = ["m.title LIKE ? ESCAPE '\\'" for _ in title_tokens]
            title_clauses.append(f"({joiner.join(like_clauses)})")
            params.extend(f"%{escape_like(token)}%" for token in title_tokens)

        if title_clauses:
            clauses.append(f"({' OR '.join(title_clauses)})")

        if filters.author_any:
            placeholders = ", ".join("?" for _ in filters.author_any)
            clauses.append(
                f"m.author_id IN (SELECT id FROM authors WHERE source_site_id IN ({placeholders}))"
            )
            params.extend(filters.author_any)

        if filters.author_not:
            placeholders = ", ".join("?" for _ in filters.author_not)
            clauses.append(
                "("
                "m.author_id IS NULL OR "
                f"m.author_id NOT IN (SELECT id FROM authors WHERE source_site_id IN ({placeholders}))"
                ")"
            )
            params.extend(filters.author_not)

        if filters.origin_any:
            placeholders = ", ".join("?" for _ in filters.origin_any)
            clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM movie_origins mo
                    JOIN origins o ON o.id = mo.origin_id
                    WHERE mo.movie_id = m.id
                """
                + f" AND o.source_site_id IN ({placeholders}))"
            )
            params.extend(filters.origin_any)

        if filters.origin_not:
            placeholders = ", ".join("?" for _ in filters.origin_not)
            clauses.append(
                """
                NOT EXISTS (
                    SELECT 1
                    FROM movie_origins mo
                    JOIN origins o ON o.id = mo.origin_id
                    WHERE mo.movie_id = m.id
                """
                + f" AND o.source_site_id IN ({placeholders}))"
            )
            params.extend(filters.origin_not)

        if filters.character_any:
            placeholders = ", ".join("?" for _ in filters.character_any)
            clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM movie_characters mc
                    JOIN characters c ON c.id = mc.character_id
                    WHERE mc.movie_id = m.id
                """
                + f" AND c.source_site_id IN ({placeholders}))"
            )
            params.extend(filters.character_any)

        if filters.character_not:
            placeholders = ", ".join("?" for _ in filters.character_not)
            clauses.append(
                """
                NOT EXISTS (
                    SELECT 1
                    FROM movie_characters mc
                    JOIN characters c ON c.id = mc.character_id
                    WHERE mc.movie_id = m.id
                """
                + f" AND c.source_site_id IN ({placeholders}))"
            )
            params.extend(filters.character_not)

        for tag_id in filters.tag_all:
            clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM movie_tags mt
                    JOIN tags t ON t.id = mt.tag_id
                    WHERE mt.movie_id = m.id AND t.source_site_id = ?
                )
                """
            )
            params.append(tag_id)

        if filters.tag_any:
            placeholders = ", ".join("?" for _ in filters.tag_any)
            clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM movie_tags mt
                    JOIN tags t ON t.id = mt.tag_id
                    WHERE mt.movie_id = m.id
                """
                + f" AND t.source_site_id IN ({placeholders}))"
            )
            params.extend(filters.tag_any)

        if filters.tag_not:
            placeholders = ", ".join("?" for _ in filters.tag_not)
            clauses.append(
                """
                NOT EXISTS (
                    SELECT 1
                    FROM movie_tags mt
                    JOIN tags t ON t.id = mt.tag_id
                    WHERE mt.movie_id = m.id
                """
                + f" AND t.source_site_id IN ({placeholders}))"
            )
            params.extend(filters.tag_not)

        if filters.published_from:
            clauses.append("m.published_at IS NOT NULL AND SUBSTR(m.published_at, 1, 10) >= ?")
            params.append(filters.published_from)

        if filters.published_to:
            clauses.append("m.published_at IS NOT NULL AND SUBSTR(m.published_at, 1, 10) <= ?")
            params.append(filters.published_to)

        if filters.min_views is not None:
            clauses.append("COALESCE(m.view_count, 0) >= ?")
            params.append(filters.min_views)

        if filters.max_views is not None:
            clauses.append("COALESCE(m.view_count, 0) <= ?")
            params.append(filters.max_views)

        if filters.min_favorites is not None:
            clauses.append("COALESCE(m.favorite_count, 0) >= ?")
            params.append(filters.min_favorites)

        if filters.max_favorites is not None:
            clauses.append("COALESCE(m.favorite_count, 0) <= ?")
            params.append(filters.max_favorites)

        return " AND ".join(clauses), params

    def _sort_clause(self, sort: str) -> str:
        if sort == "hot_desc":
            return f"{HOT_SCORE_SQL} DESC, COALESCE(m.published_at, '') DESC, m.source_site_id DESC"
        if sort == "popularity_desc":
            return f"{POPULARITY_SCORE_SQL} DESC, COALESCE(m.favorite_count, 0) DESC, m.source_site_id DESC"
        if sort == "favorites_desc":
            return "COALESCE(m.favorite_count, 0) DESC, COALESCE(m.published_at, '') DESC, m.source_site_id DESC"
        if sort == "favorites_asc":
            return "COALESCE(m.favorite_count, 0) ASC, COALESCE(m.published_at, '') ASC, m.source_site_id ASC"
        if sort == "views_desc":
            return "COALESCE(m.view_count, 0) DESC, COALESCE(m.published_at, '') DESC, m.source_site_id DESC"
        if sort == "views_asc":
            return "COALESCE(m.view_count, 0) ASC, COALESCE(m.published_at, '') ASC, m.source_site_id ASC"
        if sort == "published_asc":
            return "COALESCE(m.published_at, '') ASC, m.source_site_id ASC"
        return "COALESCE(m.published_at, '') DESC, m.source_site_id DESC"

    def _fetch_related_map(self, movie_ids: list[int], join_table: str, join_column: str, entity_table: str) -> dict[int, list[dict[str, Any]]]:
        if not movie_ids:
            return {}
        placeholders = ", ".join("?" for _ in movie_ids)
        rows = self.conn.execute(
            f"""
            SELECT rel.movie_id, ent.source_site_id AS source_id, ent.name
            FROM {join_table} rel
            JOIN {entity_table} ent ON ent.id = rel.{join_column}
            WHERE rel.movie_id IN ({placeholders})
            ORDER BY ent.name
            """,
            movie_ids,
        ).fetchall()
        mapping: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            mapping[int(row["movie_id"])].append(
                {"id": int(row["source_id"]), "name": str(row["name"])}
            )
        return mapping

    def search_movies(
        self,
        filters: SearchFilters,
        *,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        where_sql, params = self._build_search_where(filters)
        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) AS total FROM movies m WHERE {where_sql}",
                params,
            ).fetchone()["total"]
        )

        offset = (page - 1) * page_size
        rows = self.conn.execute(
            f"""
            SELECT
                m.id,
                m.source_site_id,
                m.oreno3d_url,
                m.external_video_url,
                m.title,
                m.thumbnail_url,
                m.published_at,
                m.view_count,
                m.favorite_count,
                COALESCE(a.name, m.author_display_name, 'Unknown') AS author_name,
                a.source_site_id AS author_source_id
            FROM movies m
            LEFT JOIN authors a ON a.id = m.author_id
            WHERE {where_sql}
            ORDER BY {self._sort_clause(filters.sort)}
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

        db_ids = [int(row["id"]) for row in rows]
        tags_map = self._fetch_related_map(db_ids, "movie_tags", "tag_id", "tags")
        origins_map = self._fetch_related_map(db_ids, "movie_origins", "origin_id", "origins")
        characters_map = self._fetch_related_map(db_ids, "movie_characters", "character_id", "characters")

        movies = []
        for row in rows:
            db_id = int(row["id"])
            movies.append(
                {
                    "source_site_id": int(row["source_site_id"]),
                    "oreno3d_url": str(row["oreno3d_url"]),
                    "external_video_url": row["external_video_url"],
                    "title": str(row["title"]),
                    "thumbnail_url": row["thumbnail_url"],
                    "published_at": row["published_at"],
                    "view_count": row["view_count"],
                    "favorite_count": row["favorite_count"],
                    "view_count_display": format_number(row["view_count"]),
                    "favorite_count_display": format_number(row["favorite_count"]),
                    "author_name": str(row["author_name"]),
                    "author_source_id": row["author_source_id"],
                    "tags": tags_map.get(db_id, []),
                    "origins": origins_map.get(db_id, []),
                    "characters": characters_map.get(db_id, []),
                }
            )

        return {
            "items": movies,
            "total": total,
            "page_count": page_count(total, page_size),
        }

    def get_movie(self, source_site_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT
                m.id,
                m.source_site_id,
                m.oreno3d_url,
                m.external_video_url,
                m.title,
                m.thumbnail_url,
                m.published_at,
                m.view_count,
                m.favorite_count,
                m.author_comment,
                m.status,
                COALESCE(a.name, m.author_display_name, 'Unknown') AS author_name,
                a.source_site_id AS author_source_id
            FROM movies m
            LEFT JOIN authors a ON a.id = m.author_id
            WHERE m.source_site_id = ?
            """,
            (source_site_id,),
        ).fetchone()
        if row is None:
            return None
        db_id = int(row["id"])
        tags = self._fetch_related_map([db_id], "movie_tags", "tag_id", "tags").get(db_id, [])
        origins = self._fetch_related_map([db_id], "movie_origins", "origin_id", "origins").get(db_id, [])
        characters = self._fetch_related_map([db_id], "movie_characters", "character_id", "characters").get(db_id, [])
        return {
            "source_site_id": int(row["source_site_id"]),
            "oreno3d_url": str(row["oreno3d_url"]),
            "external_video_url": row["external_video_url"],
            "title": str(row["title"]),
            "thumbnail_url": row["thumbnail_url"],
            "published_at": row["published_at"],
            "view_count": row["view_count"],
            "favorite_count": row["favorite_count"],
            "view_count_display": format_number(row["view_count"]),
            "favorite_count_display": format_number(row["favorite_count"]),
            "author_comment": row["author_comment"],
            "status": row["status"],
            "author_name": str(row["author_name"]),
            "author_source_id": row["author_source_id"],
            "tags": tags,
            "origins": origins,
            "characters": characters,
        }

    def get_related_movies(self, source_site_id: int, *, limit: int = 12) -> list[dict[str, Any]]:
        """Find related movies based on shared author, characters, origins, and tags.

        Scoring: same_author +10, each shared character +5, each shared origin +5,
        each shared tag +1.  Only candidates with score > 0 are returned.
        Ties are broken by popularity (view_count + favorite_count * 50) DESC.
        """
        # 1. Get the movie's internal id and author_id
        row = self.conn.execute(
            "SELECT id, author_id FROM movies WHERE source_site_id = ? AND status = 'active'",
            (source_site_id,),
        ).fetchone()
        if row is None:
            return []
        movie_id = int(row["id"])
        author_id = row["author_id"]

        # 2. Collect related entity ids from join tables
        character_ids = [
            int(r["character_id"])
            for r in self.conn.execute(
                "SELECT character_id FROM movie_characters WHERE movie_id = ?", (movie_id,)
            ).fetchall()
        ]
        origin_ids = [
            int(r["origin_id"])
            for r in self.conn.execute(
                "SELECT origin_id FROM movie_origins WHERE movie_id = ?", (movie_id,)
            ).fetchall()
        ]
        tag_ids = [
            int(r["tag_id"])
            for r in self.conn.execute(
                "SELECT tag_id FROM movie_tags WHERE movie_id = ?", (movie_id,)
            ).fetchall()
        ]

        # 3-6. Build candidate set, score, order, and limit in one query.
        # Candidates are movies sharing at least one dimension with the source movie.
        # We use a UNION of candidate movie_ids, then join back to compute scores.
        union_parts: list[str] = []
        params: list[Any] = []

        if author_id is not None:
            union_parts.append(
                "SELECT id AS movie_id FROM movies WHERE author_id = ? AND id != ? AND status = 'active'"
            )
            params.extend([author_id, movie_id])

        if character_ids:
            ph = ", ".join("?" for _ in character_ids)
            union_parts.append(
                f"SELECT movie_id FROM movie_characters WHERE character_id IN ({ph}) AND movie_id != ?"
            )
            params.extend(character_ids)
            params.append(movie_id)

        if origin_ids:
            ph = ", ".join("?" for _ in origin_ids)
            union_parts.append(
                f"SELECT movie_id FROM movie_origins WHERE origin_id IN ({ph}) AND movie_id != ?"
            )
            params.extend(origin_ids)
            params.append(movie_id)

        if tag_ids:
            ph = ", ".join("?" for _ in tag_ids)
            union_parts.append(
                f"SELECT movie_id FROM movie_tags WHERE tag_id IN ({ph}) AND movie_id != ?"
            )
            params.extend(tag_ids)
            params.append(movie_id)

        if not union_parts:
            return []

        candidates_sql = " UNION ".join(union_parts)

        # Build scoring sub-selects
        author_score = "0"
        author_params: list[Any] = []
        if author_id is not None:
            author_score = "CASE WHEN m.author_id = ? THEN 10 ELSE 0 END"
            author_params = [author_id]

        char_score = "0"
        char_params: list[Any] = []
        if character_ids:
            ph = ", ".join("?" for _ in character_ids)
            char_score = f"(SELECT COUNT(*) FROM movie_characters mc WHERE mc.movie_id = m.id AND mc.character_id IN ({ph})) * 5"
            char_params = list(character_ids)

        origin_score = "0"
        origin_params: list[Any] = []
        if origin_ids:
            ph = ", ".join("?" for _ in origin_ids)
            origin_score = f"(SELECT COUNT(*) FROM movie_origins mo WHERE mo.movie_id = m.id AND mo.origin_id IN ({ph})) * 5"
            origin_params = list(origin_ids)

        tag_score = "0"
        tag_params: list[Any] = []
        if tag_ids:
            ph = ", ".join("?" for _ in tag_ids)
            tag_score = f"(SELECT COUNT(*) FROM movie_tags mt WHERE mt.movie_id = m.id AND mt.tag_id IN ({ph}))"
            tag_params = list(tag_ids)

        score_expr = f"({author_score} + {char_score} + {origin_score} + {tag_score})"

        sql = f"""
            SELECT
                m.source_site_id,
                m.title,
                m.thumbnail_url,
                m.view_count,
                m.favorite_count,
                m.published_at,
                m.external_video_url,
                COALESCE(a.name, m.author_display_name, 'Unknown') AS author_name,
                {score_expr} AS rel_score,
                {POPULARITY_SCORE_SQL} AS popularity
            FROM movies m
            LEFT JOIN authors a ON a.id = m.author_id
            WHERE m.id IN (SELECT movie_id FROM ({candidates_sql}))
              AND m.status = 'active'
              AND {score_expr} > 0
            ORDER BY rel_score DESC, popularity DESC
            LIMIT ?
        """

        all_params = author_params + char_params + origin_params + tag_params + params + author_params + char_params + origin_params + tag_params + [limit]

        rows = self.conn.execute(sql, all_params).fetchall()
        return [
            {
                "source_site_id": int(r["source_site_id"]),
                "title": str(r["title"]),
                "thumbnail_url": r["thumbnail_url"],
                "view_count": r["view_count"],
                "favorite_count": r["favorite_count"],
                "view_count_display": format_number(r["view_count"]),
                "favorite_count_display": format_number(r["favorite_count"]),
                "published_at": r["published_at"],
                "external_video_url": r["external_video_url"],
                "author_name": str(r["author_name"]),
            }
            for r in rows
        ]

    def get_author_top_movies(self, author_source_ids: list[int], *, per_author: int = 6) -> dict[int, list[dict[str, Any]]]:
        if not author_source_ids:
            return {}
        result: dict[int, list[dict[str, Any]]] = {}
        for author_sid in author_source_ids:
            rows = self.conn.execute(
                f"""
                SELECT m.source_site_id, m.title, m.thumbnail_url, m.view_count, m.favorite_count,
                       COALESCE(a.name, m.author_display_name, 'Unknown') AS author_name
                FROM movies m
                JOIN authors a ON a.id = m.author_id
                WHERE a.source_site_id = ? AND m.status = 'active'
                ORDER BY {POPULARITY_SCORE_SQL} DESC
                LIMIT ?
                """,
                (author_sid, per_author),
            ).fetchall()
            result[author_sid] = [
                {"source_site_id": int(r["source_site_id"]), "title": str(r["title"]),
                 "thumbnail_url": r["thumbnail_url"],
                 "view_count_display": format_number(r["view_count"]),
                 "favorite_count_display": format_number(r["favorite_count"]),
                 "author_name": str(r["author_name"])}
                for r in rows
            ]
        return result

    def sidebar_rankings(self, *, per_section_limit: int = 12) -> dict[str, list[dict[str, Any]]]:
        return {
            "characters": self.list_entity_rankings("characters", limit=per_section_limit),
            "authors": self.list_entity_rankings("authors", limit=per_section_limit),
            "categories": self.list_category_rankings(limit=per_section_limit),
        }

    def list_entity_rankings(
        self,
        kind: EntityKind,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if kind == "authors":
            rows = self.conn.execute(
                f"""
                SELECT
                    a.source_site_id AS source_id,
                    a.name,
                    COUNT(m.id) AS movie_count,
                    COALESCE(SUM(m.view_count), 0) AS total_views,
                    COALESCE(SUM(m.favorite_count), 0) AS total_favorites,
                    COALESCE(SUM({POPULARITY_SCORE_SQL}), 0) AS popularity_score,
                    COALESCE(SUM({HOT_SCORE_SQL}), 0) AS hot_score
                FROM authors a
                JOIN movies m ON m.author_id = a.id
                WHERE m.status = 'active'
                GROUP BY a.id
                ORDER BY popularity_score DESC, total_favorites DESC, movie_count DESC, a.name
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            return [self._format_entity_ranking_row(row, kind="authors") for row in rows]

        table, join_column = self._entity_table(kind)
        join_table = f"movie_{kind}"
        rows = self.conn.execute(
            f"""
            SELECT
                ent.source_site_id AS source_id,
                ent.name,
                COUNT(DISTINCT m.id) AS movie_count,
                COALESCE(SUM(m.view_count), 0) AS total_views,
                COALESCE(SUM(m.favorite_count), 0) AS total_favorites,
                COALESCE(SUM({POPULARITY_SCORE_SQL}), 0) AS popularity_score,
                COALESCE(SUM({HOT_SCORE_SQL}), 0) AS hot_score
            FROM {table} ent
            JOIN {join_table} rel ON rel.{join_column} = ent.id
            JOIN movies m ON m.id = rel.movie_id
            WHERE m.status = 'active'
            GROUP BY ent.id
            ORDER BY popularity_score DESC, total_favorites DESC, movie_count DESC, ent.name
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [self._format_entity_ranking_row(row, kind=kind) for row in rows]

    def list_category_rankings(self, *, limit: int = 12, offset: int = 0) -> list[dict[str, Any]]:
        source_limit = limit + offset
        tags = self.list_entity_rankings("tags", limit=source_limit)
        origins = self.list_entity_rankings("origins", limit=source_limit)

        items = [
            {
                **item,
                "kind": "tags",
                "label": "Tag",
            }
            for item in tags
        ] + [
            {
                **item,
                "kind": "origins",
                "label": "原作",
            }
            for item in origins
        ]
        items.sort(
            key=lambda item: (
                float(item["popularity_score"]),
                int(item["total_favorites"]),
                int(item["movie_count"]),
                item["name"],
            ),
            reverse=True,
        )
        return items[offset: offset + limit]

    def _format_entity_ranking_row(self, row: sqlite3.Row, *, kind: str) -> dict[str, Any]:
        return {
            "kind": kind,
            "source_id": int(row["source_id"]),
            "name": str(row["name"]),
            "movie_count": int(row["movie_count"]),
            "total_views": int(row["total_views"] or 0),
            "total_favorites": int(row["total_favorites"] or 0),
            "total_views_display": format_number(row["total_views"]),
            "total_favorites_display": format_number(row["total_favorites"]),
            "popularity_score": float(row["popularity_score"] or 0),
            "hot_score": float(row["hot_score"] or 0),
        }
