# Reproducible Benchmarks (`BENCHMARKS`)

**Hardware & Runtime Environment**:
- **CPU / RAM**: Linux `6.18.57` x86_64 · `2 vCPU` (`Intel Xeon @ 2.30GHz`) · `7.8 GiB` RAM · local ext4 SSD
- **Toolchain**: Python `3.13.18` · SQLite `3.53.1` · Docker `29.10.0`
- **Dataset**: Deterministic synthetic seed (`seed=42`, [`scripts/bench_200k.py`](../../scripts/bench_200k.py)): `200,000` movies, `~1,000,000` `movie_tags` links, `200,000` `movie_characters` links, `200,000` `movie_origins` links, `5,000` authors, `2,000` tags, `3,000` characters, `500` origins.
- **Reproduction Command**:
  ```bash
  uv run python scripts/bench_200k.py --output /tmp/metrics.json
  ```

---

## Before (`v0.2.2` / `97fb04d`, Schema v4) vs. After (Schema v5 + Milestones 1–3)

### 1. Storage Footprint, Migration & Peak Memory

| Metric | Baseline (v4) | After (v5) | Delta / Speedup | Notes |
|---|---:|---:|---:|---|
| Raw v1 seed size | `68.64 MB` | `68.64 MB` | `0.0%` | Identical 200k synthetic seed (`seed=42`) |
| **Migrated DB size** | **`327.42 MB`** | **`231.42 MB`** | **`-29.3%` (`-96.0 MB`)** | Eliminated shadow `%_content` tables & `'missing'` FTS rows |
| `movie_search` total FTS5 | `113.13 MB` | **`87.95 MB`** | **`-22.3%`** | `content='', contentless_delete=1` (`85.11 MB` data + `2.84 MB` docsize) |
| **`movie_search_short` total FTS5** | **`79.42 MB`** | **`16.79 MB`** | **`-78.9%` (`4.73×` smaller)** | `content='', contentless_delete=1, detail=none` |
| **Migration peak process RSS** | **`2,705.37 MB`** | **`596.97 MB`** | **`-77.9%` (`4.53×` lower)** | Streamed `fetchmany(5_000)` cursor replaces eager `.fetchall()` |
| Migration wall time (`v1 → v5` + FTS `'optimize'`) | `30.43 s` | `63.66 s` | `+33.23 s` | Includes one-time FTS5 `'optimize'` segment merge into a single b-tree |
| Full `refresh_derived(full=True)` | `6,235.98 ms` | `6,679.45 ms` | `+7.1%` | Rebuilds JST `hot_score` + `entity_stats` + bounded FTS `'merge'` |
| Incremental `refresh_derived(full=False)` | `156.48 ms` | `167.45 ms` | `+7.0%` | Recent 30d JST `hot_score` refresh |
| **Online `.backup()` + `PRAGMA quick_check`** | **`8,742.02 ms`** | **`4,325.72 ms`** | **`-50.5%` (`2.02×` faster)** | Faster page copy & integrity check from `-96 MB` compact DB |
| Container image size | `275.26 MB` | `275.3 MB` | `0.0%` | Non-root `searchiwara` runtime |

### 2. Storage Query Latencies (`N = 60` Warm Runs + Cold First Run)

| Operation | Baseline Cold (`ms`) | After Cold (`ms`) | Baseline P50 (`ms`) | After P50 (`ms`) | Baseline P95 (`ms`) | After P95 (`ms`) | Speedup (P50) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **`search_default_latest`** | `2.737` | **`1.431`** | `1.425` | **`0.719`** | `1.535` | **`0.832`** | **`1.98×`** |
| **`search_hot_desc`** | `2.503` | **`1.443`** | `1.478` | **`0.750`** | `1.568` | **`0.819`** | **`1.97×`** |
| **`search_deep_page_277`** | `2.864` | **`1.995`** | `1.913` | **`1.171`** | `2.319` | **`1.643`** | **`1.63×`** |
| `search_fts_latin` (`"yelan dance"`) | `87.061` | `82.580` | `56.018` | `55.859` | `66.796` | `63.306` | `1.00×` |
| `search_fts_cjk_trigram` (`"キヴォトス"`) | `106.702` | `104.112` | `83.980` | `83.374` | `87.333` | `86.216` | `1.01×` |
| `search_fts_cjk_2char` (`"水着"`) | `79.421` | `78.551` | `57.820` | `57.214` | `62.331` | `63.889` | `1.01×` |
| `search_fts_cjk_1char` (`"夏"`) | `88.494` | `89.981` | `67.493` | `67.547` | `72.772` | `81.659` | `1.00×` |
| `search_fts_mixed_all` (`"yelan 水着"`) | `145.296` | `138.685` | `105.612` | `104.322` | `112.027` | `108.000` | `1.01×` |
| `search_fts_mixed_any` (`"初音 dance"`) | `199.522` | `192.807` | `164.482` | `161.787` | `182.321` | `167.837` | `1.02×` |
| **`search_tag_all_and_not`** (`tag_all=[1,3], tag_not=[2]`) | **`312.847`** | **`241.675`** | **`261.307`** | **`90.305`** | **`278.664`** | **`98.937`** | **`2.89×`** |
| `search_high_freq_tag_not` (`tag_not=[1]`) | `444.858` | **`381.795`** | `145.562` | **`138.116`** | `153.260` | `164.548` | `1.05×` |
| `search_date_and_views` | `127.997` | `140.199` | `38.652` | `38.104` | `43.662` | `40.607` | `1.01×` |
| `detail_get_movie` | `0.424` | `0.356` | `0.057` | `0.064` | `0.109` | `0.097` | `1.0×` |
| **`detail_related_movies`** (incl. tags) | **`59.629`** | **`17.796`** | **`41.095`** | **`8.894`** | **`44.399`** | **`9.403`** | **`4.62×`** |
| `rankings_facet_workbench` | `0.378` | `0.414` | `0.193` | `0.172` | `0.259` | `0.233` | `1.12×` |
| `rankings_categories_p10` | `1.539` | `1.595` | `1.376` | `1.368` | `1.481` | `1.425` | `1.01×` |
| **`rankings_authors_top_movies`** (`5` authors) | `1.793` | **`0.726`** | `0.792` | **`0.393`** | `0.840` | **`0.479`** | **`2.02×`** |
| **`rankings_dataset_status`** | **`13.872`** | **`0.105`** | **`10.888`** | **`0.021`** | **`11.315`** | **`0.024`** | **`518×`** |
| `autocomplete_tags_prefix` (`"dan"`) | `0.591` | `0.667` | `0.305` | `0.327` | `0.367` | `0.450` | `1.0×` |

### 3. End-to-End HTTP + Jinja2 + GZip Latencies (`N = 40` Runs)

| Endpoint | Baseline P50 (`ms`) | After P50 (`ms`) | Baseline P95 (`ms`) | After P95 (`ms`) | Notes |
|---|---:|---:|---:|---:|---|
| `GET /` | `21.378` | `23.419` | `23.017` | `25.158` | Cached full-corpus workbench (`limit=5`) |
| `GET /?q=yelan+dance` | `76.755` | `141.354` | `80.649` | `146.385` | **Intentional trade-off**: now computes live result-scoped facets across 4 taxonomies (`SearchStore.facet_counts`, sampled at `1,000` matches) instead of static global counts |
| **`GET /?tag_all=1,3&tag_not=2`** | **`279.749`** | **`179.658`** | **`290.497`** | **`200.616`** | **`1.56×` faster** *even while* computing live result-scoped dynamic facets |
| **`GET /movies/123456`** | **`52.946`** | **`23.649`** | **`55.973`** | **`27.713`** | **`2.24×` faster** (`MATERIALIZED` + `CROSS JOIN` `related_movies`, now also rendering card tags) |
| **`GET /authors`** (`60` authors) | `134.447` | `134.337` | **`243.854`** | **`154.030`** | **`-36.8%` P95 tail latency** via `idx_movies_author_top` bounded seeks |
| `GET /categories` | `10.751` | `14.701` | `11.695` | `19.518` | Includes new directory search bar & 5-mode sort toolbar |
| `GET /api/tags?query=dan&counts=1` | `3.042` | `5.441` | `3.726` | `7.640` | Sub-8ms with NFKC normalization |
| `GET /readyz` | `1.819` | `3.820` | `2.889` | `7.829` | Sub-8ms schema + table readability check |

### 4. Multi-Thread Concurrency (`16` Reader Threads on `2` vCPUs)

| Workload | Baseline QPS | After QPS | Baseline P95 (`ms`) | After P95 (`ms`) | Baseline P99 (`ms`) | After P99 (`ms`) | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| **`320` concurrent mixed reads** | `30.5` | **`51.5` (`+68.9%`)** | `2,136.866` | **`824.270` (`2.59×` faster)** | `2,235.276` | **`863.494` (`2.59×` faster)** | `0` |
| **`320` reads + `200` concurrent movie batch writes** | `29.6` | **`47.5` (`+60.5%`)** | `2,168.905` | **`869.174` (`2.50×` faster)** | `2,330.672` | **`917.560` (`2.54×` faster)** | `0` |

---

## Key Engineering Insights from Benchmarking

1. **`tag_all` Cardinality Ordering + PK `EXISTS` (`2.89×` speedup)**: Rewriting `tag_all` to look up `entity_stats` cardinalities first, drive a subquery from the rarest required tag (`idx_movie_tags_reverse`), and check remaining required/excluded tags via `sqlite_autoindex_movie_tags_1(movie_id, tag_id)` cut `search_tag_all_and_not` P50 from `261.3 ms` to `90.3 ms` and lifted 16-thread mixed read throughput by `+68.9%`.
2. **`related_movies` `MATERIALIZED` + `CROSS JOIN` (`4.62×` speedup)**: Pinning SQLite's join order outward from the single source movie eliminated planner sensitivity while simultaneously fixing `missing` source-movie recommendations and loading tag chips on related cards (`52.9 ms` → `23.6 ms` E2E).
3. **`app_meta['active_movies']` Trigger + Unfiltered Short-Circuit (`518×` & `1.98×` speedups)**: Maintaining exact active movie count via ACID status triggers eliminated the `11 ms` `COUNT(*)` index scan on every unfiltered `/` load, `/sitemap.xml` request, and Prometheus `/metrics` scrape.
4. **High-Fanout Entity Rename Guard (`INLINE_REINDEX_CAP`)**: Synthetic Pareto/Zipf stress testing revealed that renaming a mega-tag attached to >100,000 movies inline inside `apply_movie_detail` would hold a single SQLite write transaction for >2 minutes. Capping inline `index_movies_batch` at `500` movies and deferring larger renames via `app_meta['fts_dirty'] = '1'` to `refresh_derived(full=True)` keeps individual crawl batch commits sub-second while guaranteeing full FTS consistency at sync completion.
