# ADR-0002: Dual SQLite FTS5 (`contentless_delete`) + Precomputed Read Models over External Search Engines

- **Status**: Accepted
- **Date**: 2026-11-25

## Context

Search Iwara requires substring and token search across mixed Japanese, Chinese, Korean, and Latin scripts (`1`-char CJK, `2`-char CJK/Latin, `3+`-char substring) combined with boolean `all`/`any`/`not` entity filters and 8 deterministic sort modes on ~200,000–500,000 movies.

We evaluated:
1. **Option A**: Single-file SQLite WAL + Dual FTS5 (`movie_search` trigram + `movie_search_short` unicode61 `prefix='1 2'`) + materialized read models (`entity_stats`, `movies.hot_score`, `app_meta['active_movies']`), upgraded to Schema v5.
2. **Option B**: External search sidecar (Meilisearch / Typesense / Elasticsearch).
3. **Option C**: PostgreSQL + `pg_trgm` / `pgroonga`.

## Evidence

- Baseline v4 stored `192.55 MB` of FTS data inside a `327.42 MB` 200k-movie DB (`58.8%`) due to unused `%_content` shadow tables and `detail=full` token offsets in `movie_search_short`. Empirical benchmarks on SQLite `3.53.1` showed `content='', contentless_delete=1` (+ `detail=none` on `movie_search_short`, keeping `detail=full` on `movie_search` per SQLite FTS5 §4.3.4) cuts FTS disk usage by **55.4%** while retaining `DELETE`, `optimize`, and `integrity-check`.
- Keeping relational tables and FTS5 inside one SQLite ACID transaction avoids cross-system dual-write drift and enables single-file online backups (`sqlite3.Connection.backup()`), whereas Meilisearch/PostgreSQL would double or triple minimum VPS memory (`512 MB–1 GB` → `2–4 GB`).

## Decision

**Adopt Option A (Schema v5)**:
1. Rebuild `movie_search` (`trigram`, `content=''`, `contentless_delete=1` when SQLite >= 3.43) and `movie_search_short` (`content=''`, `contentless_delete=1`, `detail=none` when SQLite >= 3.43) over `status = 'active'` rows only, streaming via `fetchmany(5_000)` to cap migration RSS `< 600 MB`.
2. Enforce FTS consistency on `mark_movie_missing()`, `suppress_movies()`, and `_upsert_entity()` renames; run FTS `'optimize'` on full refresh; set `PRAGMA journal_size_limit = 67108864`.
3. Add `idx_movies_author_top(author_id, status, popularity DESC, source_site_id DESC)`, `app_meta['active_movies']`, cardinality-ordered `tag_all` `EXISTS`, single-pass page-1 `search()` when `< page_size`, JST `+9 hours` `hot_score` decay, and `MATERIALIZED` + `CROSS JOIN` in `related_movies()`.
