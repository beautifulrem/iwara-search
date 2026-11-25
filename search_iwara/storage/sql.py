"""SQL fragments shared by the write side, the read side and migrations."""

from __future__ import annotations

import sqlite3
from typing import Final

from ..models import EntityKind, SortMode


def active_movie_count(conn: sqlite3.Connection) -> int:
    """O(1) lookup of active movie count maintained by v5 triggers, with COUNT(*) fallback."""

    row = conn.execute("SELECT value FROM app_meta WHERE key = 'active_movies'").fetchone()
    if row is not None:
        return int(row[0])
    return int(conn.execute("SELECT COUNT(*) FROM movies WHERE status = 'active'").fetchone()[0])


# (entity table, join table, join column) — identifiers are whitelisted here and nowhere else.
ENTITY_TABLES: Final[dict[EntityKind, tuple[str, str, str]]] = {
    "authors": ("authors", "", "author_id"),
    "tags": ("tags", "movie_tags", "tag_id"),
    "origins": ("origins", "movie_origins", "origin_id"),
    "characters": ("characters", "movie_characters", "character_id"),
}
RELATION_KINDS: Final[tuple[EntityKind, ...]] = ("tags", "origins", "characters")

POPULARITY_EXPR: Final = "(COALESCE(view_count, 0) + COALESCE(favorite_count, 0) * 50)"

# "Hot" decays popularity by age in hours (HN-style gravity with a 6h grace period).
# ``published_at`` is stored in naive Asia/Tokyo (UTC+9) wall time, so compare against +9h.
HOT_SCORE_UPDATE: Final = """
UPDATE movies
SET hot_score = popularity / (
    MAX(
        (julianday(datetime('now', '+9 hours')) - julianday(COALESCE(published_at, '1970-01-01 00:00')))
        * 24.0,
        0.0
    ) + 6.0
)
WHERE status = 'active'
"""
# Older movies' hot scores drift negligibly between syncs (score ∝ 1/age), so runs without
# catalogue changes only refresh the last 30 days (in Asia/Tokyo date coordinates).
HOT_SCORE_UPDATE_RECENT: Final = (
    HOT_SCORE_UPDATE + "  AND published_at >= date('now', '+9 hours', '-30 days')\n"
)

ACTIVE_MOVIES_REFRESH: Final = """
INSERT INTO app_meta(key, value)
VALUES ('active_movies', CAST((SELECT COUNT(*) FROM movies WHERE status = 'active') AS TEXT))
ON CONFLICT(key) DO UPDATE SET value = excluded.value
"""

BUMP_DATA_REVISION: Final = """
INSERT INTO app_meta(key, value) VALUES ('data_revision', '1')
ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(app_meta.value AS INTEGER) + 1 AS TEXT)
"""

# One searchable document per movie: the title plus every human-facing name attached to it.
SEARCH_DOCUMENT_SELECT: Final = """
SELECT
    m.id AS rowid,
    m.title AS title,
    TRIM(
        COALESCE(a.name, m.author_display_name, '') || ' ' ||
        COALESCE((SELECT group_concat(c.name, ' ') FROM movie_characters mc
                  JOIN characters c ON c.id = mc.character_id WHERE mc.movie_id = m.id), '') || ' ' ||
        COALESCE((SELECT group_concat(o.name, ' ') FROM movie_origins mo
                  JOIN origins o ON o.id = mo.origin_id WHERE mo.movie_id = m.id), '') || ' ' ||
        COALESCE((SELECT group_concat(t.name, ' ') FROM movie_tags mt
                  JOIN tags t ON t.id = mt.tag_id WHERE mt.movie_id = m.id), '')
    ) AS keywords
FROM movies m
LEFT JOIN authors a ON a.id = m.author_id
"""

ENTITY_STATS_REFRESH: Final[tuple[str, ...]] = (
    "DELETE FROM entity_stats",
    """
    INSERT INTO entity_stats (
        kind, source_id, name, movie_count, total_views, total_favorites, popularity, hot
    )
    SELECT 'authors', a.source_site_id, a.name, COUNT(*), COALESCE(SUM(m.view_count), 0),
           COALESCE(SUM(m.favorite_count), 0), COALESCE(SUM(m.popularity), 0),
           COALESCE(SUM(m.hot_score), 0)
    FROM movies m JOIN authors a ON a.id = m.author_id
    WHERE m.status = 'active'
    GROUP BY a.id
    """,
    *(
        f"""
        INSERT INTO entity_stats (
            kind, source_id, name, movie_count, total_views, total_favorites, popularity, hot
        )
        SELECT '{kind}', e.source_site_id, e.name, COUNT(*), COALESCE(SUM(m.view_count), 0),
               COALESCE(SUM(m.favorite_count), 0), COALESCE(SUM(m.popularity), 0),
               COALESCE(SUM(m.hot_score), 0)
        FROM {join_table} rel
        JOIN {table} e ON e.id = rel.{column}
        JOIN movies m ON m.id = rel.movie_id
        WHERE m.status = 'active'
        GROUP BY e.id
        """
        for kind, (table, join_table, column) in ENTITY_TABLES.items()
        if join_table
    ),
)

# Every ORDER BY below is served by a composite index created in migration 2.
SORT_CLAUSES: Final[dict[SortMode, str]] = {
    "published_desc": "m.published_at DESC, m.source_site_id DESC",
    "published_asc": "m.published_at ASC, m.source_site_id ASC",
    "favorites_desc": "m.favorite_count DESC, m.published_at DESC, m.source_site_id DESC",
    "favorites_asc": "m.favorite_count ASC, m.published_at ASC, m.source_site_id ASC",
    "views_desc": "m.view_count DESC, m.published_at DESC, m.source_site_id DESC",
    "views_asc": "m.view_count ASC, m.published_at ASC, m.source_site_id ASC",
    "popularity_desc": "m.popularity DESC, m.source_site_id DESC",
    "hot_desc": "m.hot_score DESC, m.source_site_id DESC",
}
