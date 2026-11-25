# Progress Log (`PROGRESS`)

Chronological engineering log of baselines, experiments, milestones, adversarial review findings, and verifications.

---

## 2026-11-25 — Phase 0–5: Baseline, Research, Independent Audit & Architecture Decisions

- **Environment & Baseline**:
  - Verified hardware/runtime: Linux 6.18.57 x86_64 (`2 vCPU` Intel Xeon @ 2.30GHz, `7.8 GiB` RAM, SQLite `3.53.1`, Node `v22.23.5`, Docker `29.10.0`).
  - Synced to `origin/main` `97fb04d` (`v0.2.2` + Dependabot & pytest 9.2 updates). All baseline checks pass (`303` unit/property tests at `95.89%` coverage, `20` slow tests, `52` Chromium E2E tests, `0` `pip-audit` advisories, baseline Docker image `275.26 MB`).
- **200,000-Movie Baseline Benchmark (`baseline_metrics.json`)**:
  - Uncovered four major database/memory bottlenecks: `search_tag_all_and_not` = `261.3 ms` P50 (`2,136.9 ms` 16-thread P95); `GET /authors` = `134.4 ms` P50 (`243.9 ms` P95); `detail_related_movies` = `41.1 ms` P50 (full 200k scan of `idx_movies_hot`); `migrate` peak RSS = `2,705.4 MB` with `327.42 MB` DB size (`192.55 MB` FTS alone).
- **FTS5 Empirical Storage Experiment (5,000 docs, SQLite `3.53.1`)**:
  - Verified `contentless_delete=1` is incompatible with `columnsize=0` (`OperationalError`), whereas `content='', contentless_delete=1` (+ `detail=none` on `movie_search_short`) passes all `MATCH`, `DELETE`, `optimize`, and `integrity-check` operations while shrinking FTS disk usage by **55.4%** (`2.96 MiB` → `1.32 MiB`).
- **Independent `frontend-reviewer` Subagent Audit**:
  - Ran isolated Principal Product Designer subagent over 29 live Chromium screenshots across desktop, tablet, mobile, dark/light, `zh-Hans`/`ja`/`en`, keyboard, and No-JS. Verdict: *Design direction sound; Conditional Pass pending 5 `P1` UX fixes* (`AUD-007`–`AUD-011`) plus `P2` input/detail/responsive refinements (`AUD-013`).
- **Architecture Decisions Recorded**:
  - [ADR-0001](../adr/0001-modular-monolith-ssr.md): Retain Python + FastAPI + Jinja2 SSR + Progressive Vanilla JS modular monolith.
  - [ADR-0002](../adr/0002-sqlite-dual-fts5-read-models.md): Dual SQLite FTS5 (`contentless_delete=1`) + precomputed read models & v5 query optimizations.
  - [ADR-0003](../adr/0003-polite-single-writer-sync-and-compliance.md): Polite single-writer crawler, validated redirect/size guards & `suppressed` compliance tombstones.

---

## 2026-11-25 — Phase 7: Atomic Milestone Implementation (`M0`–`M3`)

- **Milestone 0 (`6cfc392`)**:
  - Created `docs/evolution/{RESEARCH,AUDIT,ROADMAP,EXECPLAN,BENCHMARKS,PROGRESS}.md`, `docs/adr/0001..0003.md`, and `scripts/bench_200k.py`.
  - Removed `9.5 MiB` `design-evidence/` scratch artifacts and 4 superseded root `DESIGN_*.md` files.
- **Milestone 1 (`f43c3b6`) — Storage Schema v5, FTS5 Consistency, Query Plans & Compliance**:
  - Upgraded `SCHEMA_VERSION` to `5`: `content='', contentless_delete=1` FTS5 (`detail=none` on `movie_search_short`), active-only FTS indexing, streamed `fetchmany(5_000)` rebuilds, `idx_movies_author_top`, ACID `app_meta['active_movies']` triggers, and `journal_size_limit = 64 MiB`.
  - Fixed JST (`+9 hours`) skew in `hot_score` and stale-detail queries, Unicode NFKC entity lookups, FTS consistency on entity renames and `missing` transitions, `tag_all` rarest-tag + PK `EXISTS` plan, `MATERIALIZED` + `CROSS JOIN` `related_movies` (including `missing` source movies & batched tags), `SearchStore.facet_counts()`, `RankingStore` `q`/`sort`, `db suppress|unsuppress|reindex`, and a 200-example Hypothesis Search Oracle test.
- **Milestone 2 (`f4094bb`) — Crawler Guards, Web HTTP Semantics & Deploy Hardening**:
  - Added 5-hop origin + `robots.txt` redirect validation and `2 MiB`/`10 MiB` streaming body limits in `Oreno3dClient`.
  - Fixed `ui_lang` `Set-Cookie` on `304`, canonical `303` & inverted-range normalization before `ETag`, `HEAD` across `/api/{kind}` & ops routes, and `/readyz` `StorageError` -> `503`.
  - Hardened Docker `sync-loop.sh`/`backup-loop.sh` (`SIGTERM` traps + immediate sync), nginx `/static/` security headers & immutable cache map, and `alert_webhook` SSRF validation.
- **Milestone 3 (`fd1e41d`) — Frontend UX, Dynamic Facets, Directory Search/Sort & Mobile Ergonomics**:
  - Shipped result-scoped dynamic workbench facets preserving active query context, searchable & 5-way sortable entity directories with progressive `<details>` on `/authors`, live filter-sheet group counts across all 5 `<details>` sections, `.is-dropup` combobox popups, visible mobile `.brand`, on-screen mobile `Clear all filters`, `>= 16px` coarse inputs, un-clipped `60fps` badges, pending-detail status notice, and safe `https://` linkification in author notes (`322` unit/web/property tests at `95.75%` coverage + `52/52` Chromium E2E + `axe-core` tests passing).

---

## 2026-11-25 — Phase 8–10: Post-Benchmark Tuning, Adversarial Reviews & Final Verification (`M4`)

- **Pareto Mega-Tag Discovery & Storage Tuning**:
  - Initial 200k post-upgrade benchmark uncovered an edge case where renaming a Zipf-top tag (`~170k` movies) inline during `apply_movie_detail` held a write lock for ~180s, and unconditional FTS `'optimize'` rewrote 85 MB on every `refresh_derived(full=True)`.
  - Capped inline entity-rename reindexing at `INLINE_REINDEX_CAP = 500` (deferring mega-entity renames via `app_meta['fts_dirty'] = '1'` to `refresh_derived(full=True)`), replaced unconditional `'optimize'` with bounded `merge_indexes(pages=64)`, and deduplicated `_v2`/`_v3` migration builds when upgrading straight to `v5`.
- **Clean 200,000-Movie Before vs. After Benchmark (`after_metrics.json`)**:
  - DB size: `327.42 MB` → **`231.42 MB` (`-29.3%`)**; `movie_search_short`: `79.42 MB` → **`16.79 MB` (`-78.9%`)**.
  - Post-migrate peak RSS: `2,705.37 MB` → **`596.97 MB` (`4.53×` lower)**; online backup + `quick_check`: `8.74 s` → **`4.33 s` (`2.02×` faster)**.
  - `search_tag_all_and_not` P50: `261.31 ms` → **`90.31 ms` (`2.89×` faster)**; `detail_related_movies` P50: `41.10 ms` → **`8.89 ms` (`4.62×` faster)**; `dataset_status`: `10.89 ms` → **`0.021 ms` (`518×` faster)**; `GET /authors` P95: `243.85 ms` → **`154.03 ms` (`-36.8%`)**.
  - 16-thread concurrent reads: `30.5 QPS` (P95 `2,136.9 ms`) → **`51.5 QPS` (`+68.9%`, P95 `824.3 ms`)**; mixed read+write: `29.6 QPS` → **`47.5 QPS` (`+60.5%`, `0` errors)**.
- **Independent Phase 8 Adversarial Reviews & Re-Verification (`PASS` × 2)**:
  - **`arch-security-db-reviewer`**: Initial audit surfaced 4 `P1`, 6 `P2`, and 4 `P3` edge cases (mixed 2-char CJK↔ASCII search `MIXED_BIGRAM_RE`, `/movies/{id}` 404-before-304 + monotonic `data_revision`, Docker `sync-loop.sh`/`backup-loop.sh` child `SIGTERM` forwarding, CLI `_cli_write_lock` `EXIT_LOCKED` 75, `_v5` `<3.43` FTS rebuild check, `unsuppress` `'missing'`/stub handling, SARGable `low > 0` count ranges, crawler TLS-downgrade/port/`Content-Length` guards, `run-alert.sh` `_NoRedirectHandler` + metadata IP guards, `HEAD` `303` parity + `Vary: Referer`, `ReadOnlyPool` inode tracking, and `utils.py` host decoupling). All 14 resolved with regression tests; re-verification verdict: **`PASS` (`0 P0 · 0 P1 · 0 P2`)**.
  - **`frontend-reviewer`**: Initial 39-screenshot Chromium review surfaced 3 `P1`, 4 `P2`, and 1 `P3` UI/UX issues (`/authors`, `.detail__comment`, and mobile `.filter-chip` `.sr-only` horizontal overflows; mobile 2-column short-tag `M...` truncation and `[+` `+N` slicing; `linkify_comment` CJK URL boundary; `.is-dropup` combobox positioning & ambiguous input guard; disjunctive `ANY` facet union candidates, active remove labels & `72rem` sticky threshold; compact mobile `.taxonomy` & direct-visit `sessionStorage` cleanup; strict `?q=&sort=` directory ordering, `/categories` desktop nav & stateful `/authors` summary). All resolved; 17-screenshot re-verification verdict: **`PASS` (`0 P0 · 0 P1 · 0 P2`)**.
- **Screenshots & Documentation Sync**:
  - Regenerated all 6 work-safe screenshots in `docs/assets/screenshots/*.jpg` and synced `README.md`, `README.zh-CN.md`, `CHANGELOG.md`, `SECURITY.md`, `DESIGN.md`, and `docs/{architecture,configuration,troubleshooting,accessibility}.md`.
