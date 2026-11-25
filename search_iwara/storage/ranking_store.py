"""Read side: rankings (served from the ``entity_stats`` read model) and dataset status."""

from __future__ import annotations

import sqlite3
from typing import Any, Final

from ..models import (
    DEFAULT_RANKING_SORT,
    DatasetStatus,
    EntityKind,
    MovieCard,
    RankingKind,
    RankingRow,
    RankingSort,
)
from ..utils import clean_text, escape_like
from .mappers import CARD_COLUMNS, load_cards
from .sql import active_movie_count

RANKING_SORT_CLAUSES: Final[dict[RankingSort, str]] = {
    "popularity": "popularity DESC, total_favorites DESC, movie_count DESC, name",
    "hot": "hot DESC, popularity DESC, movie_count DESC, name",
    "movies": "movie_count DESC, popularity DESC, total_favorites DESC, name",
    "favorites": "total_favorites DESC, popularity DESC, movie_count DESC, name",
    "views": "total_views DESC, popularity DESC, movie_count DESC, name",
}
RANK_COLUMNS: Final = "kind, source_id, name, movie_count, total_views, total_favorites, popularity, hot"
FACET_KINDS: Final[tuple[EntityKind, ...]] = ("characters", "tags", "authors", "origins")


def _kind_and_query_filter(kind: RankingKind, q: str = "") -> tuple[str, list[Any]]:
    if kind == "categories":
        clauses = ["kind IN (?, ?)"]
        params: list[Any] = ["tags", "origins"]
    else:
        clauses = ["kind = ?"]
        params = [kind]
    cleaned = clean_text(q)
    if cleaned:
        clauses.append("name LIKE ? ESCAPE '\\'")
        params.append(f"%{escape_like(cleaned)}%")
    return " AND ".join(clauses), params


class RankingStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.conn = connection

    def count(self, kind: RankingKind, *, q: str = "") -> int:
        where, params = _kind_and_query_filter(kind, q)
        return int(
            self.conn.execute(f"SELECT COUNT(*) FROM entity_stats WHERE {where}", params).fetchone()[0]
        )

    def top(
        self,
        kind: RankingKind,
        *,
        limit: int,
        offset: int = 0,
        q: str = "",
        sort: RankingSort = DEFAULT_RANKING_SORT,
    ) -> list[RankingRow]:
        where, params = _kind_and_query_filter(kind, q)
        order_sql = RANKING_SORT_CLAUSES[sort]
        rows = self.conn.execute(
            f"SELECT {RANK_COLUMNS} FROM entity_stats WHERE {where} ORDER BY {order_sql} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [
            RankingRow(
                kind=row["kind"],
                source_id=int(row["source_id"]),
                name=str(row["name"]),
                movie_count=int(row["movie_count"]),
                total_views=int(row["total_views"]),
                total_favorites=int(row["total_favorites"]),
                popularity=int(row["popularity"]),
                hot=float(row["hot"]),
            )
            for row in rows
        ]

    def facet_workbench(self, *, limit: int = 5) -> dict[EntityKind, list[RankingRow]]:
        return {kind: self.top(kind, limit=limit) for kind in FACET_KINDS}

    def top_movies_by_author(
        self, author_ids: list[int], *, per_author: int = 8
    ) -> dict[int, list[MovieCard]]:
        """Top ``per_author`` active movies per author via bounded seeks on ``idx_movies_author_top``."""

        if not author_ids:
            return {}
        placeholders = ", ".join("?" * len(author_ids))
        rows = self.conn.execute(
            f"""
            SELECT {CARD_COLUMNS}
            FROM authors a
            CROSS JOIN movies m ON m.id IN (
                SELECT m2.id
                FROM movies m2
                WHERE m2.author_id = a.id AND m2.status = 'active'
                ORDER BY m2.popularity DESC, m2.source_site_id DESC
                LIMIT ?
            )
            WHERE a.source_site_id IN ({placeholders})
            ORDER BY a.id, m.popularity DESC, m.source_site_id DESC
            """,
            (per_author, *author_ids),
        ).fetchall()
        cards = load_cards(self.conn, rows)
        result: dict[int, list[MovieCard]] = {author_id: [] for author_id in author_ids}
        for card in cards:
            if card.author_id is not None:
                result[card.author_id].append(card)
        return result

    def dataset_status(self) -> DatasetStatus:
        movie_count = active_movie_count(self.conn)
        last_success = self.conn.execute(
            "SELECT MAX(finished_at) FROM sync_runs WHERE status IN ('success', 'partial')"
        ).fetchone()[0]
        last_run = self.conn.execute(
            "SELECT started_at, status, requests, retries, throttled FROM sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return DatasetStatus(
            movie_count=movie_count,
            last_success_at=last_success,
            last_run_at=None if last_run is None else last_run["started_at"],
            last_run_status=None if last_run is None else last_run["status"],
            last_run_requests=0 if last_run is None else int(last_run["requests"]),
            last_run_retries=0 if last_run is None else int(last_run["retries"]),
            last_run_throttled=0 if last_run is None else int(last_run["throttled"]),
        )
