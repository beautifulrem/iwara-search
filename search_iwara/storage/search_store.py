"""Read side: search, detail, related movies and autocomplete."""

from __future__ import annotations

import sqlite3
from typing import Any, Final

from ..models import EntityKind, EntityLink, MovieCard, MovieDetailView, SearchFilters, SearchPage
from ..utils import escape_like, page_count, split_query_tokens
from .mappers import CARD_COLUMNS, load_cards, load_relations
from .search_index import is_cjk
from .sql import ENTITY_TABLES, SORT_CLAUSES

MAX_QUERY_TOKENS: Final = 8
TRIGRAM_MIN_LENGTH: Final = 3

# filter field -> (entity kind, mode)
ENTITY_FILTERS: Final[tuple[tuple[str, EntityKind, str], ...]] = (
    ("author_any", "authors", "any"),
    ("author_not", "authors", "not"),
    ("origin_any", "origins", "any"),
    ("origin_not", "origins", "not"),
    ("character_any", "characters", "any"),
    ("character_not", "characters", "not"),
    ("tag_all", "tags", "all"),
    ("tag_any", "tags", "any"),
    ("tag_not", "tags", "not"),
)


def _movies_with_entities_sql(kind: EntityKind, count: int) -> str:
    """Sub-select of movie ids linked to any of ``count`` entity source ids."""

    table, join_table, column = ENTITY_TABLES[kind]
    placeholders = ", ".join("?" * count)
    if kind == "authors":
        return (
            "SELECT m2.id FROM movies m2 JOIN authors e ON e.id = m2.author_id "
            f"WHERE e.source_site_id IN ({placeholders})"
        )
    return (
        f"SELECT rel.movie_id FROM {join_table} rel JOIN {table} e ON e.id = rel.{column} "
        f"WHERE e.source_site_id IN ({placeholders})"
    )


def uses_trigram(connection: sqlite3.Connection) -> bool:
    row = connection.execute("SELECT value FROM app_meta WHERE key = 'fts_tokenizer'").fetchone()
    return row is not None and row["value"] == "trigram"


def _fts_phrase(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


class SearchStore:
    def __init__(self, connection: sqlite3.Connection, *, trigram: bool | None = None) -> None:
        self.conn = connection
        self.trigram = uses_trigram(connection) if trigram is None else trigram

    # --- search ------------------------------------------------------------------------------

    def _text_clause(self, filters: SearchFilters) -> tuple[str | None, list[Any]]:
        """Route each token to an index; no query shape falls back to a table scan.

        * >= 3 characters: trigram FTS (substring match, any script);
        * 1-2 CJK characters: exact n-gram token in ``movie_search_short``;
        * 1-2 other characters: indexed word-prefix match in ``movie_search_short``.
        """

        tokens = split_query_tokens(filters.q)[:MAX_QUERY_TOKENS]
        if not tokens:
            return None, []
        joiner = " OR " if filters.title_mode == "any" else " AND "
        long_tokens = [t for t in tokens if len(t) >= TRIGRAM_MIN_LENGTH]
        short_tokens = [t for t in tokens if len(t) < TRIGRAM_MIN_LENGTH]
        parts: list[str] = []
        params: list[Any] = []
        if long_tokens and self.trigram:
            parts.append("m.id IN (SELECT rowid FROM movie_search WHERE movie_search MATCH ?)")
            params.append(joiner.join(_fts_phrase(token) for token in long_tokens))
        elif long_tokens:  # SQLite < 3.34: no trigram tokenizer, substring LIKE instead
            for token in long_tokens:
                parts.append(
                    "m.id IN (SELECT rowid FROM movie_search "
                    "WHERE title LIKE ? ESCAPE '\\' OR keywords LIKE ? ESCAPE '\\')"
                )
                like = f"%{escape_like(token)}%"
                params.extend((like, like))
        if short_tokens:
            parts.append("m.id IN (SELECT rowid FROM movie_search_short WHERE movie_search_short MATCH ?)")
            params.append(
                joiner.join(
                    _fts_phrase(token) if is_cjk(token) else _fts_phrase(token) + "*"
                    for token in short_tokens
                )
            )
        return "(" + joiner.join(parts) + ")", params

    def _entity_clause(self, kind: EntityKind, mode: str, ids: list[int]) -> tuple[list[str], list[Any]]:
        if mode == "all":
            return [f"m.id IN ({_movies_with_entities_sql(kind, 1)})" for _ in ids], list(ids)
        if kind == "authors":
            operator = "NOT IN" if mode == "not" else "IN"
            return [f"m.id {operator} ({_movies_with_entities_sql(kind, len(ids))})"], list(ids)
        table, join_table, column = ENTITY_TABLES[kind]
        ph = ", ".join("?" * len(ids))
        entity_rows = self.conn.execute(
            f"SELECT e.id, COALESCE(s.movie_count, 0) FROM {table} e "
            f"LEFT JOIN entity_stats s ON s.kind = ? AND s.source_id = e.source_site_id "
            f"WHERE e.source_site_id IN ({ph})",
            (kind, *ids),
        ).fetchall()
        if not entity_rows:
            return (["0"], []) if mode == "any" else ([], [])
        internal_ids = [int(r[0]) for r in entity_rows]
        est_links = sum(int(r[1]) for r in entity_rows)
        int_ph = ", ".join("?" * len(internal_ids))
        if est_links > 25_000:
            prefix = "NOT EXISTS" if mode == "not" else "EXISTS"
            sql = (
                f"{prefix} (SELECT 1 FROM {join_table} rel "
                f"WHERE rel.movie_id = m.id AND rel.{column} IN ({int_ph}))"
            )
            return [sql], internal_ids
        operator = "NOT IN" if mode == "not" else "IN"
        sql = f"m.id {operator} (SELECT rel.movie_id FROM {join_table} rel WHERE rel.{column} IN ({int_ph}))"
        return [sql], internal_ids

    def build_where(self, filters: SearchFilters) -> tuple[str, list[Any]]:
        clauses = ["m.status = 'active'"]
        params: list[Any] = []

        text_clause, text_params = self._text_clause(filters)
        if text_clause:
            clauses.append(text_clause)
            params.extend(text_params)

        for field_name, kind, mode in ENTITY_FILTERS:
            ids: list[int] = getattr(filters, field_name)
            if ids:
                extra_clauses, extra_params = self._entity_clause(kind, mode, ids)
                clauses.extend(extra_clauses)
                params.extend(extra_params)

        if filters.published_from:
            clauses.append("m.published_at >= ?")
            params.append(filters.published_from)
        if filters.published_to:
            clauses.append("m.published_at < date(?, '+1 day')")
            params.append(filters.published_to)
        for column, low, high in (
            ("view_count", filters.min_views, filters.max_views),
            ("favorite_count", filters.min_favorites, filters.max_favorites),
        ):
            if low is not None:
                clauses.append(f"COALESCE(m.{column}, 0) >= ?")
                params.append(low)
            if high is not None:
                clauses.append(f"COALESCE(m.{column}, 0) <= ?")
                params.append(high)
        return " AND ".join(clauses), params

    def search(self, filters: SearchFilters, *, page: int, page_size: int, max_results: int) -> SearchPage:
        """One page of results. Counting stops at ``max_results`` so deep scans stay bounded."""

        where_sql, params = self.build_where(filters)
        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) FROM (SELECT 1 FROM movies m WHERE {where_sql} LIMIT ?)",
                [*params, max_results + 1],
            ).fetchone()[0]
        )
        capped = total > max_results
        total = min(total, max_results)
        pages = page_count(total, page_size)
        page = min(max(page, 1), pages)
        page_ids = [
            int(r[0])
            for r in self.conn.execute(
                f"""
                SELECT m.id
                FROM movies m
                WHERE {where_sql}
                ORDER BY {SORT_CLAUSES[filters.sort]}
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        ]
        rows: list[sqlite3.Row] = []
        if page_ids:
            id_ph = ", ".join("?" * len(page_ids))
            fetched = {
                int(r["id"]): r
                for r in self.conn.execute(
                    f"""
                    SELECT {CARD_COLUMNS}
                    FROM movies m LEFT JOIN authors a ON a.id = m.author_id
                    WHERE m.id IN ({id_ph})
                    """,
                    page_ids,
                ).fetchall()
            }
            rows = [fetched[mid] for mid in page_ids if mid in fetched]
        return SearchPage(
            items=load_cards(self.conn, rows, with_tags=True),
            total=total,
            total_is_capped=capped,
            page=page,
            page_count=pages,
        )

    # --- cards & detail ----------------------------------------------------------------------

    def get_movie(self, source_site_id: int) -> MovieDetailView | None:
        row = self.conn.execute(
            f"""
            SELECT {CARD_COLUMNS}, m.oreno3d_url, m.external_video_url, m.author_comment, m.status,
                   m.detail_fetched_at
            FROM movies m LEFT JOIN authors a ON a.id = m.author_id
            WHERE m.source_site_id = ?
            """,
            (source_site_id,),
        ).fetchone()
        if row is None:
            return None
        movie_id = int(row["id"])
        relations = {
            kind: load_relations(self.conn, kind, [movie_id]).get(movie_id, ())
            for kind in ("tags", "origins", "characters")
        }
        card = load_cards(self.conn, [row])[0]
        return MovieDetailView(
            card=card,
            oreno3d_url=str(row["oreno3d_url"]),
            external_video_url=row["external_video_url"],
            author_comment=row["author_comment"],
            status="missing" if row["status"] == "missing" else "active",
            detail_fetched_at=row["detail_fetched_at"],
            tags=relations["tags"],
            origins=relations["origins"],
            characters=relations["characters"],
        )

    def related_movies(self, source_site_id: int, *, limit: int = 12) -> list[MovieCard]:
        """Weighted neighbours: same author +10, shared character/origin +5 each, shared tag +1.

        Candidates are gathered once with their weights (UNION ALL) and summed per movie, so
        each score is computed exactly once; ties are broken by popularity. Entities attached
        to more than 5% of the catalogue are ignored (IDF-style): they say little about
        similarity and would otherwise make the candidate set as large as the catalogue.
        """

        weights: tuple[tuple[EntityKind, int], ...] = (("characters", 5), ("origins", 5), ("tags", 1))
        branches = []
        for kind, weight in weights:
            table, join_table, column = ENTITY_TABLES[kind]
            branches.append(
                f"""
                SELECT o.movie_id, {weight}
                FROM src
                JOIN {join_table} s ON s.movie_id = src.id
                JOIN {table} e ON e.id = s.{column}
                LEFT JOIN entity_stats es ON es.kind = '{kind}' AND es.source_id = e.source_site_id
                JOIN {join_table} o ON o.{column} = s.{column}
                WHERE o.movie_id != src.id AND COALESCE(es.movie_count, 0) <= src.fanout_cap
                """
            )
        rows = self.conn.execute(
            f"""
            WITH src AS (
                SELECT id, author_id,
                       MAX(100, (SELECT COUNT(*) FROM movies WHERE status = 'active') / 20) AS fanout_cap
                FROM movies WHERE source_site_id = ? AND status = 'active'
            ),
            weighted(movie_id, weight) AS (
                SELECT m.id, 10 FROM src JOIN movies m ON m.author_id = src.author_id AND m.id != src.id
                UNION ALL {" UNION ALL ".join(branches)}
            ),
            scored AS (
                SELECT movie_id, SUM(weight) AS score FROM weighted GROUP BY movie_id
            )
            SELECT {CARD_COLUMNS}
            FROM scored s
            JOIN movies m ON m.id = s.movie_id
            LEFT JOIN authors a ON a.id = m.author_id
            WHERE m.status = 'active'
            ORDER BY s.score DESC, m.popularity DESC, m.source_site_id DESC
            LIMIT ?
            """,
            (source_site_id, limit),
        ).fetchall()
        return load_cards(self.conn, rows)

    # --- entities ----------------------------------------------------------------------------

    def autocomplete_with_counts(
        self, kind: EntityKind, query: str, *, limit: int = 10
    ) -> list[tuple[EntityLink, int]]:
        table = ENTITY_TABLES[kind][0]
        cleaned = query.strip()
        if not cleaned:
            rows = self.conn.execute(
                "SELECT source_id AS id, name, movie_count FROM entity_stats WHERE kind = ? "
                "ORDER BY popularity DESC, name LIMIT ?",
                (kind, limit),
            ).fetchall()
        else:
            like = f"%{escape_like(cleaned)}%"
            rows = self.conn.execute(
                f"""
                SELECT e.source_site_id AS id, e.name, COALESCE(s.movie_count, 0) AS movie_count
                FROM {table} e
                LEFT JOIN entity_stats s ON s.kind = ? AND s.source_id = e.source_site_id
                WHERE e.name LIKE ? ESCAPE '\\'
                ORDER BY INSTR(LOWER(e.name), LOWER(?)) = 1 DESC, COALESCE(s.popularity, 0) DESC, e.name
                LIMIT ?
                """,
                (kind, like, cleaned, limit),
            ).fetchall()
        return [(EntityLink(int(row["id"]), str(row["name"])), int(row["movie_count"])) for row in rows]

    def autocomplete(self, kind: EntityKind, query: str, *, limit: int = 10) -> list[EntityLink]:
        return [item for item, _ in self.autocomplete_with_counts(kind, query, limit=limit)]

    def resolve_entity_names(
        self, kind: EntityKind, raw_text: str, *, limit: int = 5
    ) -> tuple[list[int], list[str]]:
        """Resolve comma-separated entity names (or numeric IDs) typed without JS selection."""

        table = ENTITY_TABLES[kind][0]
        phrases = [part.strip() for part in raw_text.replace("，", ",").replace("、", ",").split(",")]
        phrases = [part for part in phrases if part][:limit]
        matched: list[int] = []
        unmatched: list[str] = []
        seen: set[int] = set()
        for phrase in phrases:
            if phrase.isascii() and phrase.isdigit():
                candidate_id = int(phrase)
                exists = self.conn.execute(
                    f"SELECT source_site_id FROM {table} WHERE source_site_id = ?",
                    (candidate_id,),
                ).fetchone()
                if exists is not None:
                    if candidate_id not in seen:
                        seen.add(candidate_id)
                        matched.append(candidate_id)
                    continue
            like = f"%{escape_like(phrase)}%"
            row = self.conn.execute(
                f"""
                SELECT e.source_site_id AS id
                FROM {table} e
                LEFT JOIN entity_stats s ON s.kind = ? AND s.source_id = e.source_site_id
                WHERE e.name LIKE ? ESCAPE '\\'
                ORDER BY LOWER(e.name) = LOWER(?) DESC,
                         INSTR(LOWER(e.name), LOWER(?)) = 1 DESC,
                         COALESCE(s.popularity, 0) DESC,
                         e.source_site_id
                LIMIT 1
                """,
                (kind, like, phrase, phrase),
            ).fetchone()
            if row is None:
                unmatched.append(phrase)
            else:
                entity_id = int(row["id"])
                if entity_id not in seen:
                    seen.add(entity_id)
                    matched.append(entity_id)
        return matched, unmatched

    def resolve_entities(self, kind: EntityKind, source_ids: list[int]) -> list[EntityLink]:
        if not source_ids:
            return []
        table = ENTITY_TABLES[kind][0]
        placeholders = ", ".join("?" * len(source_ids))
        rows = self.conn.execute(
            f"SELECT source_site_id, name FROM {table} WHERE source_site_id IN ({placeholders})",
            source_ids,
        ).fetchall()
        lookup = {int(row["source_site_id"]): str(row["name"]) for row in rows}
        return [EntityLink(item, lookup[item]) for item in source_ids if item in lookup]
