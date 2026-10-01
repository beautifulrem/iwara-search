"""Versioned schema migrations keyed on ``PRAGMA user_version``.

Migrations run exactly once per database, inside a transaction each, from
``search-iwara db migrate`` or the web app's lifespan start-up — never per request.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from ..parsers import SOURCE_HOSTS, VIDEO_HOSTS
from ..utils import decode_source_escapes, safe_url
from .connection import trigram_supported
from .search_index import rebuild_short_index
from .sql import ENTITY_STATS_REFRESH, HOT_SCORE_UPDATE, SEARCH_DOCUMENT_SELECT

logger = logging.getLogger(__name__)

Migration = Callable[[sqlite3.Connection], None]


def _v1_baseline(conn: sqlite3.Connection) -> None:
    """The original (0.1.x) schema, minus its title-only FTS table (replaced in v2)."""

    entity_tables = "\n".join(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_site_id INTEGER NOT NULL UNIQUE,
            name TEXT NOT NULL,
            oreno3d_url TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );"""
        for table in ("authors", "tags", "origins", "characters")
    )
    join_tables = "\n".join(
        f"""
        CREATE TABLE IF NOT EXISTS movie_{kind} (
            movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
            {column} INTEGER NOT NULL REFERENCES {kind}(id) ON DELETE CASCADE,
            PRIMARY KEY (movie_id, {column})
        );"""
        for kind, column in (("tags", "tag_id"), ("origins", "origin_id"), ("characters", "character_id"))
    )
    statements = f"""
        {entity_tables}
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
        {join_tables}
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
    """
    for statement in statements.split(";"):
        if statement.strip():
            conn.execute(statement)


def _v2_search_stats_and_indexes(conn: sqlite3.Connection) -> None:
    # 1. Drop the title-only unicode61 FTS (it could not match CJK substrings).
    for trigger in ("movies_ai", "movies_ad", "movies_au"):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    conn.execute("DROP TABLE IF EXISTS movie_fts")

    # 2. Scores used for sorting: popularity is derived, hot decays with time (refreshed per sync).
    conn.execute(
        "ALTER TABLE movies ADD COLUMN popularity INTEGER GENERATED ALWAYS AS "
        "(COALESCE(view_count, 0) + COALESCE(favorite_count, 0) * 50) VIRTUAL"
    )
    conn.execute("ALTER TABLE movies ADD COLUMN hot_score REAL NOT NULL DEFAULT 0")

    # 3. Failure bookkeeping for capped, spaced-out retries.
    conn.execute("ALTER TABLE crawl_errors ADD COLUMN error_type TEXT")
    conn.execute("ALTER TABLE crawl_errors ADD COLUMN next_retry_at TEXT")

    # 4. Replace single-column indexes with composite ones that serve WHERE status + ORDER BY.
    for index in (
        "idx_movies_source_site_id",
        "idx_movies_status",
        "idx_movies_published_at",
        "idx_movies_favorite_count",
        "idx_movies_view_count",
        "idx_tags_source_site_id",
        "idx_authors_source_site_id",
        "idx_origins_source_site_id",
        "idx_characters_source_site_id",
        "idx_crawl_errors_lookup",
    ):
        conn.execute(f"DROP INDEX IF EXISTS {index}")
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_movies_author_id ON movies(author_id)",
        "CREATE INDEX idx_movies_published ON movies(status, published_at DESC, source_site_id DESC)",
        "CREATE INDEX idx_movies_favorites ON movies(status, favorite_count DESC, published_at DESC)",
        "CREATE INDEX idx_movies_views ON movies(status, view_count DESC, published_at DESC)",
        "CREATE INDEX idx_movies_popularity ON movies(status, popularity DESC, source_site_id DESC)",
        "CREATE INDEX idx_movies_hot ON movies(status, hot_score DESC, source_site_id DESC)",
        "CREATE INDEX idx_movies_detail_fetched ON movies(status, detail_fetched_at)",
        "CREATE INDEX idx_movie_tags_reverse ON movie_tags(tag_id, movie_id)",
        "CREATE INDEX idx_movie_origins_reverse ON movie_origins(origin_id, movie_id)",
        "CREATE INDEX idx_movie_characters_reverse ON movie_characters(character_id, movie_id)",
        "CREATE INDEX idx_crawl_errors_retry ON crawl_errors(entity_type, operation, next_retry_at)",
    ):
        conn.execute(statement)

    # 5. Full-text search over title + author/character/origin/tag names.
    tokenizer = "trigram" if trigram_supported() else "unicode61"
    if tokenizer != "trigram":
        logger.warning(
            "SQLite < 3.34: trigram tokenizer unavailable, CJK substring search falls back to LIKE"
        )
    conn.execute(f"CREATE VIRTUAL TABLE movie_search USING fts5(title, keywords, tokenize='{tokenizer}')")
    conn.execute(f"INSERT INTO movie_search(rowid, title, keywords) {SEARCH_DOCUMENT_SELECT}")

    # 6. Materialised read models and run history.
    conn.execute(
        """
        CREATE TABLE entity_stats (
            kind TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            movie_count INTEGER NOT NULL,
            total_views INTEGER NOT NULL,
            total_favorites INTEGER NOT NULL,
            popularity INTEGER NOT NULL,
            hot REAL NOT NULL,
            PRIMARY KEY (kind, source_id)
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        "CREATE INDEX idx_entity_stats_rank ON entity_stats"
        "(kind, popularity DESC, total_favorites DESC, movie_count DESC, name)"
    )
    conn.execute(
        """
        CREATE TABLE sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
            started_at TEXT NOT NULL,
            finished_at TEXT,
            pages_checked INTEGER NOT NULL DEFAULT 0,
            failed_pages INTEGER NOT NULL DEFAULT 0,
            movies_seen INTEGER NOT NULL DEFAULT 0,
            new_movies INTEGER NOT NULL DEFAULT 0,
            changed_movies INTEGER NOT NULL DEFAULT 0,
            details_fetched INTEGER NOT NULL DEFAULT 0,
            missing_movies INTEGER NOT NULL DEFAULT 0,
            failed_details INTEGER NOT NULL DEFAULT 0,
            error TEXT
        )
        """
    )
    conn.execute("CREATE INDEX idx_sync_runs_status ON sync_runs(status, finished_at DESC)")
    conn.execute("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID")
    conn.execute("INSERT INTO app_meta(key, value) VALUES ('fts_tokenizer', ?)", (tokenizer,))

    _sanitise_urls(conn)
    conn.execute(HOT_SCORE_UPDATE)
    for statement in ENTITY_STATS_REFRESH:
        conn.execute(statement)


def _v3_cjk_index_tiebreakers_and_run_stats(conn: sqlite3.Connection) -> None:
    # Unique tie-breakers so OFFSET pagination over equal counts is stable.
    for name, column in (("idx_movies_favorites", "favorite_count"), ("idx_movies_views", "view_count")):
        conn.execute(f"DROP INDEX IF EXISTS {name}")
        conn.execute(
            f"CREATE INDEX {name} ON movies(status, {column} DESC, published_at DESC, source_site_id DESC)"
        )
    # Crawler statistics per run (exported as Prometheus gauges).
    for column in ("requests", "retries", "throttled"):
        conn.execute(f"ALTER TABLE sync_runs ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE sync_runs ADD COLUMN status_codes TEXT")
    # Short-token index: CJK unigrams/bigrams + words with 1/2-char prefix indexes.
    conn.execute(
        "CREATE VIRTUAL TABLE movie_search_short USING fts5(terms, tokenize='unicode61', prefix='1 2')"
    )
    rebuild_short_index(conn)
    # Comments were stored with literal "\n" escapes (as rendered by the source site).
    conn.execute(
        "UPDATE movies SET author_comment = REPLACE(author_comment, '\\n', char(10)) "
        "WHERE author_comment LIKE '%\\n%'"
    )


def _v4_decode_comment_escapes(conn: sqlite3.Connection) -> None:
    """Comments stored before 0.2 kept the source's backslash escapes (``\\'``, ``\\"``, ``\\n``)."""

    rows = conn.execute(
        "SELECT id, author_comment FROM movies WHERE instr(author_comment, char(92)) > 0"
    ).fetchall()
    conn.executemany(
        "UPDATE movies SET author_comment = ? WHERE id = ?",
        [(decode_source_escapes(row["author_comment"]), row["id"]) for row in rows],
    )


def _sanitise_urls(conn: sqlite3.Connection) -> None:
    """Null out any URL stored by 0.1.x that the parser allow-list would now reject."""

    rows = conn.execute("SELECT id, oreno3d_url, external_video_url, thumbnail_url FROM movies").fetchall()
    for row in rows:
        video = safe_url(row["external_video_url"], VIDEO_HOSTS)
        thumbnail = safe_url(row["thumbnail_url"], SOURCE_HOSTS)
        source = safe_url(row["oreno3d_url"], SOURCE_HOSTS) or ""
        stored = (row["external_video_url"], row["thumbnail_url"], row["oreno3d_url"])
        if (video, thumbnail, source) != stored:
            conn.execute(
                "UPDATE movies SET external_video_url = ?, thumbnail_url = ?, oreno3d_url = ? WHERE id = ?",
                (video, thumbnail, source, row["id"]),
            )


MIGRATIONS: tuple[Migration, ...] = (
    _v1_baseline,
    _v2_search_stats_and_indexes,
    _v3_cjk_index_tiebreakers_and_run_stats,
    _v4_decode_comment_escapes,
)
SCHEMA_VERSION = len(MIGRATIONS)


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the number applied. Safe to call repeatedly."""

    version = current_version(conn)
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema v{version} is newer than this build (v{SCHEMA_VERSION}); upgrade search-iwara"
        )
    applied = 0
    for number, migration in enumerate(MIGRATIONS[version:], start=version + 1):
        logger.info("applying schema migration v%d (%s)", number, migration.__name__)
        conn.execute("BEGIN IMMEDIATE")
        try:
            migration(conn)
            conn.execute(f"PRAGMA user_version = {number}")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        applied += 1
    if applied:
        conn.execute("PRAGMA optimize")
    return applied
