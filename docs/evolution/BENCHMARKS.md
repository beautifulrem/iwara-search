# Reproducible Benchmarks (`BENCHMARKS`)

**Hardware & Runtime Environment**:
- **CPU / RAM**: Linux `6.18.57` x86_64 · `2 vCPU` (`Intel Xeon @ 2.30GHz`) · `7.8 GiB` RAM · local ext4 SSD
- **Toolchain**: Python `3.13.18` · SQLite `3.53.1` · Docker `29.10.0`
- **Dataset**: Deterministic synthetic seed (`seed=42`, `scripts/bench_200k.py`): `200,000` movies, `~1,000,000` `movie_tags` links, `200,000` `movie_characters` links, `200,000` `movie_origins` links, `5,000` authors, `2,000` tags, `3,000` characters, `500` origins.
- **Reproduction Command**:
  ```bash
  uv run python scripts/bench_200k.py --output /tmp/metrics.json
  ```

---

## Baseline Metrics (`v0.2.2` / `97fb04d`, Schema v4)

> Post-implementation ("After") columns will be populated in Phase 7 by running the exact same harness on the same machine.

### 1. Storage Footprint, Migration & Peak Memory

| Metric | Baseline (v4) | Target | Notes |
|---|---:|---:|---|
| Raw v1 seed size | `68.64 MB` | — | 200k movies + relations without FTS/indexes |
| Migrated DB size | **`327.42 MB`** | `< 240 MB` | Baseline includes `192.55 MB` of FTS5 tables (`58.8%`) |
| `movie_search` (`_data` + `_content`) | `113.13 MB` | `< 90 MB` | `85.26 MB` data + `27.87 MB` duplicated content |
| `movie_search_short` (`_data` + `_content`) | `79.42 MB` | `< 35 MB` | `43.82 MB` data + `35.60 MB` duplicated content |
| Migration wall time (`v1 → current`) | `30.43 s` | `<= 40 s` | Full FTS + derived stats build |
| Peak process RSS | **`2,705.37 MB`** | `< 600 MB` | Spiked by eager `.fetchall()` on 200k FTS rows |
| Full `refresh_derived(full=True)` | `6,235.98 ms` | `<= 7,500 ms` | Rebuilds `hot_score` + `entity_stats` |
| Incremental `refresh_derived(full=False)` | `156.48 ms` | `<= 250 ms` | Recent 30d `hot_score` + `entity_stats` |
| Online `.backup()` + `PRAGMA quick_check` | `8,742.02 ms` | `< 7,000 ms` | Scales directly with DB file size |
| Container image size | `275.26 MB` | `<= 285 MB` | Non-root `searchiwara` runtime |

### 2. Storage Query Latencies (`N = 60` Warm Runs + Cold Run)

| Operation | Cold (`ms`) | Warm P50 (`ms`) | Warm P95 (`ms`) | Warm P99 (`ms`) |
|---|---:|---:|---:|---:|
| `search_default_latest` | `2.737` | `1.425` | `1.535` | `1.681` |
| `search_hot_desc` | `2.503` | `1.478` | `1.568` | `1.627` |
| `search_deep_page_277` | `2.864` | `1.913` | `2.319` | `2.652` |
| `search_fts_latin` (`"yelan dance"`) | `87.061` | `56.018` | `66.796` | `69.077` |
| `search_fts_cjk_trigram` (`"キヴォトス"`) | `106.702` | `83.980` | `87.333` | `88.021` |
| `search_fts_cjk_2char` (`"水着"`) | `79.421` | `57.820` | `62.331` | `73.514` |
| `search_fts_cjk_1char` (`"夏"`) | `88.494` | `67.493` | `72.772` | `73.183` |
| `search_fts_mixed_all` (`"yelan 水着"`) | `145.296` | `105.612` | `112.027` | `121.060` |
| `search_fts_mixed_any` (`"初音 dance"`) | `199.522` | `164.482` | `182.321` | `188.946` |
| **`search_tag_all_and_not`** (`tag_all=[1,3], tag_not=[2]`) | **`312.847`** | **`261.307`** | **`278.664`** | **`280.221`** |
| `search_high_freq_tag_not` (`tag_not=[1]`) | `444.858` | `145.562` | `153.260` | `155.192` |
| `search_date_and_views` | `127.997` | `38.652` | `43.662` | `56.825` |
| `detail_get_movie` | `0.424` | `0.057` | `0.109` | `0.153` |
| **`detail_related_movies`** | **`59.629`** | **`41.095`** | **`44.399`** | **`46.113`** |
| `rankings_facet_workbench` | `0.378` | `0.193` | `0.259` | `0.267` |
| `rankings_categories_p10` | `1.539` | `1.376` | `1.481` | `1.503` |
| `rankings_authors_top_movies` (`5` authors) | `1.793` | `0.792` | `0.840` | `0.912` |
| **`rankings_dataset_status`** | **`13.872`** | **`10.888`** | **`11.315`** | **`11.712`** |
| `autocomplete_tags_prefix` (`"dan"`) | `0.591` | `0.305` | `0.367` | `0.384` |

### 3. End-to-End HTTP + Jinja2 + GZip Latencies (`N = 40` Runs)

| Endpoint | P50 (`ms`) | P95 (`ms`) | P99 (`ms`) |
|---|---:|---:|---:|
| `GET /` | `21.378` | `23.017` | `26.621` |
| `GET /?q=yelan+dance` | `76.755` | `80.649` | `92.940` |
| **`GET /?tag_all=1,3&tag_not=2`** | **`279.749`** | **`290.497`** | **`297.161`** |
| **`GET /movies/123456`** | **`52.946`** | **`55.973`** | **`57.684`** |
| **`GET /authors`** (`60` authors) | **`134.447`** | **`243.854`** | **`270.469`** |
| `GET /categories` | `10.751` | `11.695` | `17.052` |
| `GET /api/tags?query=dan&counts=1` | `3.042` | `3.726` | `4.647` |
| `GET /readyz` | `1.819` | `2.889` | `4.277` |

### 4. Multi-Thread Concurrency (`16` Reader Threads on `2` vCPUs)

| Workload | Throughput (`QPS`) | Errors | P50 (`ms`) | P95 (`ms`) | P99 (`ms`) |
|---|---:|---:|---:|---:|---:|
| `320` concurrent mixed reads | `30.5` | `0` | `210.711` | `2,136.866` | `2,235.276` |
| `320` reads + `200` concurrent movie batch writes | `29.6` | `0` | `174.178` | `2,168.905` | `2,330.672` |
