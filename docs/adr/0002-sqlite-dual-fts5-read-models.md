# ADR-0002: Dual SQLite FTS5 (`contentless_delete`) and Precomputed Read Models

- **Status**: Accepted
- **Date**: 2026-11-25

## Context

Search Iwara supports substring and token queries across Japanese, Chinese, Korean, and Latin text (`1–2` character CJK queries, `1–2` letter Latin word prefixes, and `3+` character substrings) combined with boolean `all`/`any`/`not` entity filters and 8 sort orders over ~200,000–500,000 records.

Alternatives considered:

1. **Single-file SQLite WAL + dual FTS5 + materialised read models** (`Schema v5`).
2. **External search daemon** (Meilisearch, Typesense, or Elasticsearch).
3. **PostgreSQL** (`pg_trgm` / `pgroonga`).

## Decision

Keep relational tables, dual FTS5 indexes, and materialised ranking tables inside a single SQLite database, using `content='', contentless_delete=1` (SQLite 3.43+):

1. `movie_search` (`trigram`, `content='', contentless_delete=1`) indexes 3+ character substrings; `movie_search_short` (`unicode61`, `prefix='1 2'`, `content='', contentless_delete=1, detail=none`) indexes CJK unigrams/bigrams and Latin word prefixes. Dropping unused `%_content` shadow tables and positional offsets shrinks FTS storage on 200k movies by **55.4%** (`192.6 MB` -> `104.7 MB`) while keeping `DELETE` and `optimize` support.
2. Only `status = 'active'` rows live in FTS5; `missing` and `suppressed` transitions delete FTS postings in the same transaction. Streamed `fetchmany(5_000)` migrations cap peak RSS below `600 MB`.
3. `entity_stats`, JST-anchored `movies.hot_score`, and trigger-maintained `app_meta['active_movies']` serve rankings, sidebar facets, and dataset totals without full-table aggregations.

## Consequences

- Zero cross-service synchronization drift and single-file online backups (`sqlite3.Connection.backup()`), comfortable on `512 MiB–1 GiB` hosts where a separate search engine or RDBMS would double memory requirements.
