"""Read side: rankings (served from the ``entity_stats`` read model) and dataset status."""

from __future__ import annotations

import sqlite3
from typing import Final

from ..models import DatasetStatus, MovieCard, RankingKind, RankingRow
from .mappers import CARD_COLUMNS, load_cards

RANK_ORDER: Final = "popularity DESC, total_favorites DESC, movie_count DESC, name"
RANK_COLUMNS: Final = "kind, source_id, name, movie_count, total_views, total_favorites, popularity, hot"


def _kind_filter(kind: RankingKind) -> tuple[str, tuple[str, ...]]:
    if kind == "categories":
        return "kind IN (?, ?)", ("tags", "origins")
    return "kind = ?", (kind,)


class RankingStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.conn = connection

    def count(self, kind: RankingKind) -> int:
        where, params = _kind_filter(kind)
        return int(
            self.conn.execute(f"SELECT COUNT(*) FROM entity_stats WHERE {where}", params).fetchone()[0]
        )

    def top(self, kind: RankingKind, *, limit: int, offset: int = 0) -> list[RankingRow]:
        where, params = _kind_filter(kind)
        rows = self.conn.execute(
            f"SELECT {RANK_COLUMNS} FROM entity_stats WHERE {where} ORDER BY {RANK_ORDER} LIMIT ? OFFSET ?",
            (*params, limit, offset),
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

    def sidebar(self, *, limit: int = 12) -> dict[str, list[RankingRow]]:
        return {
            "characters": self.top("characters", limit=limit),
            "authors": self.top("authors", limit=limit),
            "categories": self.top("categories", limit=limit),
        }

    def top_movies_by_author(
        self, author_ids: list[int], *, per_author: int = 8
    ) -> dict[int, list[MovieCard]]:
        if not author_ids:
            return {}
        placeholders = ", ".join("?" * len(author_ids))
        rows = self.conn.execute(
            f"""
            SELECT * FROM (
                SELECT {CARD_COLUMNS},
                       ROW_NUMBER() OVER (
                           PARTITION BY a.id ORDER BY m.popularity DESC, m.source_site_id DESC
                       ) AS rn
                FROM authors a JOIN movies m ON m.author_id = a.id
                WHERE a.source_site_id IN ({placeholders}) AND m.status = 'active'
            ) WHERE rn <= ?
            """,
            (*author_ids, per_author),
        ).fetchall()
        cards = load_cards(self.conn, rows)
        result: dict[int, list[MovieCard]] = {author_id: [] for author_id in author_ids}
        for card in cards:
            if card.author_id is not None:
                result[card.author_id].append(card)
        return result

    def dataset_status(self) -> DatasetStatus:
        movie_count = int(
            self.conn.execute("SELECT COUNT(*) FROM movies WHERE status = 'active'").fetchone()[0]
        )
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
