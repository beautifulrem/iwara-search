"""Row → read-model mapping shared by the search and ranking stores."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Final

from ..models import EntityKind, EntityLink, MovieCard
from .sql import ENTITY_TABLES

CARD_COLUMNS: Final = """
    m.id, m.source_site_id, m.title, m.thumbnail_url, m.published_at,
    COALESCE(m.view_count, 0) AS view_count, COALESCE(m.favorite_count, 0) AS favorite_count,
    COALESCE(a.name, m.author_display_name, '') AS author_name, a.source_site_id AS author_id
"""


def load_relations(
    conn: sqlite3.Connection, kind: EntityKind, movie_ids: list[int]
) -> dict[int, tuple[EntityLink, ...]]:
    """Entities of ``kind`` for many movies in one query, keyed by internal movie id."""

    if not movie_ids:
        return {}
    table, join_table, column = ENTITY_TABLES[kind]
    placeholders = ", ".join("?" * len(movie_ids))
    rows = conn.execute(
        f"""
        SELECT rel.movie_id, e.source_site_id, e.name
        FROM {join_table} rel JOIN {table} e ON e.id = rel.{column}
        WHERE rel.movie_id IN ({placeholders})
        ORDER BY e.name
        """,
        movie_ids,
    ).fetchall()
    mapping: dict[int, list[EntityLink]] = defaultdict(list)
    for row in rows:
        mapping[int(row["movie_id"])].append(EntityLink(int(row["source_site_id"]), str(row["name"])))
    return {movie_id: tuple(links) for movie_id, links in mapping.items()}


def load_cards(
    conn: sqlite3.Connection, rows: list[sqlite3.Row], *, with_tags: bool = False
) -> list[MovieCard]:
    """Map ``CARD_COLUMNS`` rows to cards, optionally batch-loading their tags."""

    tags = load_relations(conn, "tags", [int(row["id"]) for row in rows]) if with_tags else {}
    return [
        MovieCard(
            source_site_id=int(row["source_site_id"]),
            title=str(row["title"]),
            thumbnail_url=row["thumbnail_url"],
            published_at=row["published_at"],
            view_count=int(row["view_count"]),
            favorite_count=int(row["favorite_count"]),
            author_name=str(row["author_name"]),
            author_id=None if row["author_id"] is None else int(row["author_id"]),
            tags=tags.get(int(row["id"]), ()),
        )
        for row in rows
    ]
