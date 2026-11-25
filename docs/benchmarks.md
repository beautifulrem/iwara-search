# 200k-Movie Benchmarks

Reproducible storage, query, HTTP, and concurrency measurements against a deterministic 200,000-movie synthetic SQLite database (`seed=42`, mixed Latin + Japanese + Chinese titles and Pareto-distributed entity relations).

Run the benchmark harness locally:

```bash
uv run python scripts/bench_200k.py --output /tmp/metrics.json
```

Environment for the reference numbers below: Linux `x86_64`, 2 vCPUs, 7.8 GiB RAM, local SSD, Python `3.13`, SQLite `3.53` (Schema v5).

## Storage & Maintenance Footprint

| Metric | Schema v4 | Schema v5 | Change | Notes |
|---|---:|---:|---:|---|
| Raw v1 seed size | `68.64 MB` | `68.64 MB` | `0.0%` | 200,000 movies before FTS/derived tables |
| **Migrated database size** | `327.42 MB` | **`231.42 MB`** | **`-29.3%` (`-96.0 MB`)** | Drops shadow `%_content` tables and `'missing'` FTS rows |
| `movie_search` (`trigram` FTS5) | `113.13 MB` | **`87.95 MB`** | `-22.3%` | `content='', contentless_delete=1` |
| `movie_search_short` (`unicode61` FTS5) | `79.42 MB` | **`16.79 MB`** | **`-78.9%`** | `content='', contentless_delete=1, detail=none` |
| **Migration peak RSS** | `2,705.37 MB` | **`596.97 MB`** | **`-77.9%`** | Streamed `fetchmany(5_000)` cursor instead of `.fetchall()` |
| Full `refresh_derived(full=True)` | `6,236 ms` | `6,679 ms` | `+7.1%` | Recomputes JST `hot_score`, `entity_stats`, and bounded FTS merge |
| Incremental `refresh_derived(full=False)` | `156 ms` | `167 ms` | `+7.0%` | Refreshes 30-day JST `hot_score` window |
| **Online `.backup()` + `PRAGMA quick_check`** | `8,742 ms` | **`4,326 ms`** | **`-50.5%`** | Smaller page count speeds up snapshot and integrity check |

## Storage Query Latencies (`N = 60` Warm Runs)

| Query | Cold (`ms`) | Warm P50 (`ms`) | Warm P95 (`ms`) |
|---|---:|---:|---:|
| `search_default_latest` (page 1) | `1.43` | `0.72` | `0.83` |
| `search_hot_desc` (page 1) | `1.44` | `0.75` | `0.82` |
| `search_deep_page_277` (offset ~10,000) | `2.00` | `1.17` | `1.64` |
| `search_fts_latin` (`"yelan dance"`) | `82.58` | `55.86` | `63.31` |
| `search_fts_cjk_trigram` (`"キヴォトス"`) | `104.11` | `83.37` | `86.22` |
| `search_fts_cjk_2char` (`"水着"`) | `78.55` | `57.21` | `63.89` |
| `search_fts_cjk_1char` (`"夏"`) | `89.98` | `67.55` | `81.66` |
| `search_fts_mixed_all` (`"yelan 水着"`) | `138.69` | `104.32` | `108.00` |
| `search_fts_mixed_any` (`"初音 dance"`) | `192.81` | `161.79` | `167.84` |
| `search_tag_all_and_not` (`tag_all=[1,3], tag_not=[2]`) | `241.68` | `90.31` | `98.94` |
| `search_high_freq_tag_not` (`tag_not=[1]`) | `381.80` | `138.12` | `164.55` |
| `search_date_and_views` | `140.20` | `38.10` | `40.61` |
| `detail_get_movie` | `0.36` | `0.06` | `0.10` |
| `detail_related_movies` (weighted CTE + tags) | `17.80` | `8.89` | `9.40` |
| `rankings_facet_workbench` | `0.41` | `0.17` | `0.23` |
| `rankings_categories_p10` | `1.60` | `1.37` | `1.43` |
| `rankings_authors_top_movies` (`5` authors) | `0.73` | `0.39` | `0.48` |
| `rankings_dataset_status` (`app_meta` trigger) | `0.11` | `0.02` | `0.02` |
| `autocomplete_tags_prefix` (`"dan"`) | `0.67` | `0.33` | `0.45` |

## End-to-End HTTP + Jinja2 + GZip Latencies (`N = 40` Runs)

| Route | P50 (`ms`) | P95 (`ms`) | Notes |
|---|---:|---:|---|
| `GET /` | `23.42` | `25.16` | Cached global facet sidebar + page 1 grid |
| `GET /?q=yelan+dance` | `141.35` | `146.39` | Includes live result-scoped facet counts across 4 taxonomies |
| `GET /?tag_all=1,3&tag_not=2` | `179.66` | `200.62` | Cardinality-ordered `tag_all` + live result-scoped facets |
| `GET /movies/123456` | `23.65` | `27.71` | Movie detail + 12 weighted related cards |
| `GET /authors` (`60` authors × top works) | `134.34` | `154.03` | Bounded per-author seeks via `idx_movies_author_top` |
| `GET /categories` | `14.70` | `19.52` | Tag + origin directory with search & sort controls |
| `GET /api/tags?query=dan&counts=1` | `5.44` | `7.64` | Prefix + substring autocomplete with work counts |
| `GET /readyz` | `3.82` | `7.83` | Schema version + read check |

## Concurrency (`16` Reader Threads on `2` vCPUs)

| Workload | Throughput (`QPS`) | P95 (`ms`) | P99 (`ms`) | Errors |
|---|---:|---:|---:|---:|
| `320` concurrent mixed reads | `51.5` | `824.3` | `863.5` | `0` |
| `320` concurrent reads + `200` batched movie writes | `47.5` | `869.2` | `917.6` | `0` |

## Key Query Design Choices

- **Cardinality-ordered `tag_all` (`2.89×` faster)**: Required-tag intersections look up `entity_stats` counts first, drive the scan from the rarest required tag (`idx_movie_tags_reverse`), and probe remaining required or excluded tags via the composite primary key `(movie_id, tag_id)`.
- **Materialised `related_movies` join order (`4.62×` faster)**: `MATERIALIZED` + `CROSS JOIN` anchors SQLite's planner outward from the single source movie's relations rather than scanning high-degree join tables.
- **`app_meta['active_movies']` triggers**: Status-transition triggers maintain the active movie count incrementally, avoiding `COUNT(*)` index scans on unfiltered `/`, `/sitemap.xml`, and `/metrics`.
- **Deferred mega-entity FTS rebuilds (`INLINE_REINDEX_CAP = 500`)**: Renaming an upstream entity attached to `<= 500` works updates FTS inline; larger renames set `app_meta['fts_dirty'] = '1'` and rebuild during `refresh_derived(full=True)` so crawl batch transactions stay sub-second.
