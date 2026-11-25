"""Read side: search, dynamic facets, detail, related movies and autocomplete."""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Final

from ..models import (
    EntityKind,
    EntityLink,
    MovieCard,
    MovieDetailView,
    RankingRow,
    SearchFilters,
    SearchPage,
)
from ..utils import clean_text, escape_like, page_count, split_query_tokens
from .mappers import CARD_COLUMNS, load_cards, load_relations
from .search_index import is_cjk
from .sql import ENTITY_TABLES, SORT_CLAUSES, active_movie_count

MAX_QUERY_TOKENS: Final = 8
TRIGRAM_MIN_LENGTH: Final = 3
FACET_SAMPLE_CAP: Final = 2_000
FACET_ORDER_KINDS: Final[tuple[EntityKind, ...]] = ("characters", "tags", "authors", "origins")

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


def _movies_with_authors_sql(count: int) -> str:
    placeholders = ", ".join("?" * count)
    return (
        "SELECT m2.id FROM movies m2 JOIN authors e ON e.id = m2.author_id "
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
        unique_ids = list(dict.fromkeys(ids))
        if kind == "authors":
            if mode == "all":
                if len(unique_ids) > 1:
                    return ["0"], []  # a movie has at most one author
                return [f"m.id IN ({_movies_with_authors_sql(1)})"], list(unique_ids)
            operator = "NOT IN" if mode == "not" else "IN"
            return [f"m.id {operator} ({_movies_with_authors_sql(len(unique_ids))})"], unique_ids

        table, join_table, column = ENTITY_TABLES[kind]
        ph = ", ".join("?" * len(unique_ids))
        entity_rows = self.conn.execute(
            f"SELECT e.id, COALESCE(s.movie_count, 0) FROM {table} e "
            f"LEFT JOIN entity_stats s ON s.kind = ? AND s.source_id = e.source_site_id "
            f"WHERE e.source_site_id IN ({ph})",
            (kind, *unique_ids),
        ).fetchall()

        if mode == "all":
            if len(entity_rows) < len(unique_ids):
                return ["0"], []
            # Drive from the rarest required entity; probe remaining ones via PK EXISTS.
            ordered = sorted(((int(r[0]), int(r[1])) for r in entity_rows), key=lambda pair: pair[1])
            first_id, first_count = ordered[0]
            clauses: list[str] = []
            out_params: list[Any] = []
            if first_count <= 25_000:
                clauses.append(f"m.id IN (SELECT rel.movie_id FROM {join_table} rel WHERE rel.{column} = ?)")
            else:
                clauses.append(
                    f"EXISTS (SELECT 1 FROM {join_table} rel WHERE rel.movie_id = m.id AND rel.{column} = ?)"
                )
            out_params.append(first_id)
            for other_id, _ in ordered[1:]:
                clauses.append(
                    f"EXISTS (SELECT 1 FROM {join_table} rel WHERE rel.movie_id = m.id AND rel.{column} = ?)"
                )
                out_params.append(other_id)
            return clauses, out_params

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

    def _fetch_page_ids(
        self, where_sql: str, params: list[Any], *, sort_sql: str, page: int, page_size: int
    ) -> list[int]:
        return [
            int(r[0])
            for r in self.conn.execute(
                f"""
                SELECT m.id
                FROM movies m
                WHERE {where_sql}
                ORDER BY {sort_sql}
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        ]

    def _bounded_count(self, where_sql: str, params: list[Any], *, max_results: int) -> tuple[int, bool]:
        if where_sql == "m.status = 'active'" and not params:
            raw_total = active_movie_count(self.conn)
        else:
            raw_total = int(
                self.conn.execute(
                    f"SELECT COUNT(*) FROM (SELECT 1 FROM movies m WHERE {where_sql} LIMIT ?)",
                    [*params, max_results + 1],
                ).fetchone()[0]
            )
        capped = raw_total > max_results
        return min(raw_total, max_results), capped

    def search(self, filters: SearchFilters, *, page: int, page_size: int, max_results: int) -> SearchPage:
        """One page of results. Counting stops at ``max_results`` and is skipped when page 1 < page_size."""

        where_sql, params = self.build_where(filters)
        sort_sql = SORT_CLAUSES[filters.sort]
        requested_page = max(page, 1)

        if requested_page == 1 and params:
            page_ids = self._fetch_page_ids(where_sql, params, sort_sql=sort_sql, page=1, page_size=page_size)
            if len(page_ids) < page_size and len(page_ids) <= max_results:
                total = len(page_ids)
                capped = False
                pages = 1
                actual_page = 1
            else:
                total, capped = self._bounded_count(where_sql, params, max_results=max_results)
                pages = page_count(total, page_size)
                actual_page = 1
                if len(page_ids) > total:
                    page_ids = page_ids[:total]
        else:
            total, capped = self._bounded_count(where_sql, params, max_results=max_results)
            pages = page_count(total, page_size)
            actual_page = min(requested_page, pages)
            page_ids = self._fetch_page_ids(
                where_sql, params, sort_sql=sort_sql, page=actual_page, page_size=page_size
            )

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
            page=actual_page,
            page_count=pages,
        )

    # --- dynamic facets ----------------------------------------------------------------------

    def facet_counts(
        self,
        filters: SearchFilters,
        *,
        limit: int = 5,
        pinned: Mapping[EntityKind, Sequence[int]] | None = None,
        sample_cap: int = FACET_SAMPLE_CAP,
    ) -> tuple[dict[EntityKind, list[RankingRow]], bool]:
        """Compute entity counts over matching movies (bounded to ``sample_cap`` for O(1) tail latency)."""

        where_sql, params = self.build_where(filters)
        sort_sql = SORT_CLAUSES[filters.sort]
        matched = self.conn.execute(
            f"SELECT m.id, m.author_id FROM movies m WHERE {where_sql} ORDER BY {sort_sql} LIMIT ?",
            [*params, sample_cap + 1],
        ).fetchall()
        is_sampled = len(matched) > sample_cap
        matched = matched[:sample_cap]
        movie_ids = [int(r[0]) for r in matched]
        author_counts = Counter(int(r[1]) for r in matched if r[1] is not None)

        result: dict[EntityKind, list[RankingRow]] = {}
        for kind in FACET_ORDER_KINDS:
            pinned_ids = list(dict.fromkeys((pinned or {}).get(kind, ())))
            result[kind] = self._facet_kind_rows(
                kind,
                movie_ids=movie_ids,
                author_counts=author_counts,
                pinned_source_ids=pinned_ids,
                limit=limit,
            )
        return result, is_sampled

    def _load_pinned_facet_rows(
        self,
        kind: EntityKind,
        *,
        movie_ids: list[int],
        author_counts: Counter[int],
        pinned_source_ids: list[int],
    ) -> tuple[list[RankingRow], set[int]]:
        if not pinned_source_ids:
            return [], set()
        table, join_table, column = ENTITY_TABLES[kind]
        pin_ph = ", ".join("?" * len(pinned_source_ids))
        meta_rows = self.conn.execute(
            f"""
            SELECT e.id AS internal_id, e.source_site_id AS source_id, e.name,
                   COALESCE(s.total_views, 0) AS total_views,
                   COALESCE(s.total_favorites, 0) AS total_favorites,
                   COALESCE(s.popularity, 0) AS popularity,
                   COALESCE(s.hot, 0.0) AS hot
            FROM {table} e
            LEFT JOIN entity_stats s ON s.kind = ? AND s.source_id = e.source_site_id
            WHERE e.source_site_id IN ({pin_ph})
            """,
            (kind, *pinned_source_ids),
        ).fetchall()
        by_source = {int(r["source_id"]): r for r in meta_rows}
        internal_counts: dict[int, int] = {}
        if movie_ids and meta_rows:
            if kind == "authors":
                internal_counts = {
                    int(r["internal_id"]): author_counts.get(int(r["internal_id"]), 0) for r in meta_rows
                }
            else:
                id_ph = ", ".join("?" * len(movie_ids))
                int_ids = [int(r["internal_id"]) for r in meta_rows]
                int_ph = ", ".join("?" * len(int_ids))
                for crow in self.conn.execute(
                    f"SELECT {column}, COUNT(*) FROM {join_table} "
                    f"WHERE {column} IN ({int_ph}) AND movie_id IN ({id_ph}) GROUP BY {column}",
                    [*int_ids, *movie_ids],
                ):
                    internal_counts[int(crow[0])] = int(crow[1])

        pinned_rows: list[RankingRow] = []
        seen_source_ids: set[int] = set()
        for sid in pinned_source_ids:
            mrow = by_source.get(sid)
            if mrow is None:
                continue
            seen_source_ids.add(sid)
            pinned_rows.append(
                RankingRow(
                    kind=kind,
                    source_id=sid,
                    name=str(mrow["name"]),
                    movie_count=internal_counts.get(int(mrow["internal_id"]), 0),
                    total_views=int(mrow["total_views"]),
                    total_favorites=int(mrow["total_favorites"]),
                    popularity=int(mrow["popularity"]),
                    hot=float(mrow["hot"]),
                )
            )
        return pinned_rows, seen_source_ids

    def _facet_kind_rows(
        self,
        kind: EntityKind,
        *,
        movie_ids: list[int],
        author_counts: Counter[int],
        pinned_source_ids: list[int],
        limit: int,
    ) -> list[RankingRow]:
        table, join_table, column = ENTITY_TABLES[kind]
        pinned_rows, seen_source_ids = self._load_pinned_facet_rows(
            kind,
            movie_ids=movie_ids,
            author_counts=author_counts,
            pinned_source_ids=pinned_source_ids,
        )
        if not movie_ids:
            return pinned_rows[: max(limit, len(pinned_rows))]

        top_candidates: list[RankingRow] = []
        fetch_limit = limit + len(seen_source_ids)
        if kind == "authors":
            if author_counts:
                top_internal = [aid for aid, _ in author_counts.most_common(fetch_limit * 2)]
                a_ph = ", ".join("?" * len(top_internal))
                arows = self.conn.execute(
                    f"""
                    SELECT e.id AS internal_id, e.source_site_id AS source_id, e.name,
                           COALESCE(s.total_views, 0) AS total_views,
                           COALESCE(s.total_favorites, 0) AS total_favorites,
                           COALESCE(s.popularity, 0) AS popularity,
                           COALESCE(s.hot, 0.0) AS hot
                    FROM authors e
                    LEFT JOIN entity_stats s ON s.kind = 'authors' AND s.source_id = e.source_site_id
                    WHERE e.id IN ({a_ph})
                    """,
                    top_internal,
                ).fetchall()
                scored_authors = sorted(
                    arows,
                    key=lambda r: (
                        -author_counts[int(r["internal_id"])],
                        -int(r["popularity"]),
                        str(r["name"]),
                    ),
                )
                for r in scored_authors:
                    sid = int(r["source_id"])
                    if sid in seen_source_ids:
                        continue
                    top_candidates.append(
                        RankingRow(
                            kind="authors",
                            source_id=sid,
                            name=str(r["name"]),
                            movie_count=author_counts[int(r["internal_id"])],
                            total_views=int(r["total_views"]),
                            total_favorites=int(r["total_favorites"]),
                            popularity=int(r["popularity"]),
                            hot=float(r["hot"]),
                        )
                    )
        else:
            id_ph = ", ".join("?" * len(movie_ids))
            crows = self.conn.execute(
                f"""
                SELECT e.source_site_id AS source_id, e.name, COUNT(*) AS cnt,
                       COALESCE(s.total_views, 0) AS total_views,
                       COALESCE(s.total_favorites, 0) AS total_favorites,
                       COALESCE(s.popularity, 0) AS popularity,
                       COALESCE(s.hot, 0.0) AS hot
                FROM {join_table} rel
                JOIN {table} e ON e.id = rel.{column}
                LEFT JOIN entity_stats s ON s.kind = ? AND s.source_id = e.source_site_id
                WHERE rel.movie_id IN ({id_ph})
                GROUP BY e.id
                ORDER BY cnt DESC, popularity DESC, e.name ASC
                LIMIT ?
                """,
                (kind, *movie_ids, fetch_limit),
            ).fetchall()
            for r in crows:
                sid = int(r["source_id"])
                if sid in seen_source_ids:
                    continue
                top_candidates.append(
                    RankingRow(
                        kind=kind,
                        source_id=sid,
                        name=str(r["name"]),
                        movie_count=int(r["cnt"]),
                        total_views=int(r["total_views"]),
                        total_favorites=int(r["total_favorites"]),
                        popularity=int(r["popularity"]),
                        hot=float(r["hot"]),
                    )
                )

        remaining = max(0, limit - len(pinned_rows))
        return pinned_rows + top_candidates[:remaining]

    # --- cards & detail ----------------------------------------------------------------------

    def get_movie(self, source_site_id: int) -> MovieDetailView | None:
        row = self.conn.execute(
            f"""
            SELECT {CARD_COLUMNS}, m.oreno3d_url, m.external_video_url, m.author_comment, m.status,
                   m.detail_fetched_at
            FROM movies m LEFT JOIN authors a ON a.id = m.author_id
            WHERE m.source_site_id = ? AND m.status != 'suppressed'
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

        Works for both ``active`` and ``missing`` source movies (only ``active`` candidates are
        returned) so archived pages still recommend watchable works. ``MATERIALIZED`` + ``CROSS JOIN``
        pins SQLite's join order from the single source movie outward without scanning ``movies``.
        """

        fanout_cap = max(100, active_movie_count(self.conn) // 20)
        weights: tuple[tuple[EntityKind, int], ...] = (("characters", 5), ("origins", 5), ("tags", 1))
        branches = []
        for kind, weight in weights:
            table, join_table, column = ENTITY_TABLES[kind]
            branches.append(
                f"""
                SELECT o.movie_id, {weight}
                FROM src
                CROSS JOIN {join_table} s ON s.movie_id = src.id
                CROSS JOIN {table} e ON e.id = s.{column}
                LEFT JOIN entity_stats es ON es.kind = '{kind}' AND es.source_id = e.source_site_id
                CROSS JOIN {join_table} o ON o.{column} = s.{column}
                WHERE o.movie_id != src.id AND COALESCE(es.movie_count, 0) <= src.fanout_cap
                """
            )
        rows = self.conn.execute(
            f"""
            WITH src AS MATERIALIZED (
                SELECT id, author_id, ? AS fanout_cap
                FROM movies
                WHERE source_site_id = ? AND status != 'suppressed'
            ),
            weighted(movie_id, weight) AS (
                SELECT m.id, 10
                FROM src
                CROSS JOIN movies m ON m.author_id = src.author_id AND m.status = 'active'
                WHERE m.id != src.id
                UNION ALL {" UNION ALL ".join(branches)}
            ),
            scored AS (
                SELECT movie_id, SUM(weight) AS score FROM weighted GROUP BY movie_id
            )
            SELECT {CARD_COLUMNS}
            FROM scored s
            CROSS JOIN movies m ON m.id = s.movie_id
            LEFT JOIN authors a ON a.id = m.author_id
            WHERE m.status = 'active'
            ORDER BY s.score DESC, m.popularity DESC, m.source_site_id DESC
            LIMIT ?
            """,
            (fanout_cap, source_site_id, limit),
        ).fetchall()
        return load_cards(self.conn, rows, with_tags=True)

    # --- entities ----------------------------------------------------------------------------

    def autocomplete_with_counts(
        self, kind: EntityKind, query: str, *, limit: int = 10
    ) -> list[tuple[EntityLink, int]]:
        table = ENTITY_TABLES[kind][0]
        cleaned = clean_text(query)
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
        phrases = [clean_text(part) for part in raw_text.replace("，", ",").replace("、", ",").split(",")]
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
