# Engineering Evolution Roadmap & Execution Plan

**Baseline**: `v0.2.2` (`97fb04d`) · **Target**: `v0.3.0` Release-Ready Evolution  
**Guiding Principles**: Evidence over assumptions · Correctness before optimization · Simplicity over unnecessary complexity · Verification over self-assessment.

---

## 1. Strategic Roadmap (`ROADMAP`)

### Short-Term (Executed in This Autonomous Evolution Cycle)
- **M0 — Engineering Memory & Repo Hygiene**: Establish `docs/evolution/` (`RESEARCH.md`, `AUDIT.md`, `ROADMAP.md`, `EXECPLAN.md`, `BENCHMARKS.md`, `PROGRESS.md`) and `docs/adr/0001..0003.md`; remove `9.5 MiB` `design-evidence/` and root process clutter (`AUD-014`).
- **M1 — Storage v5, Search Integrity, JST Scoring, Query Optimization & Compliance Tombstones**: Fix FTS5 consistency (`AUD-001`), JST timezone decay (`AUD-002`), NFKC entity lookup (`AUD-003`), 200k SQLite bottlenecks & 2.7 GiB migration RSS (`AUD-004`), `missing`-page related videos (`AUD-011`), and `db suppress`/`unsuppress`/`reindex` (`AUD-012`), backed by Hypothesis Search Oracle Equivalence tests.
- **M2 — Crawler RFC 9309 Safety, Web HTTP Semantics & Deployment Hardening**: Bounded validated redirects & response byte caps (`AUD-005`), HTTP `304`/`HEAD`/`/readyz`/`COOP`/`CORP` fixes (`AUD-006`), Docker loop `SIGTERM` + immediate first sync, Nginx `/static/` security headers, and webhook validation (`AUD-014`).
- **M3 — Frontend IA, Dynamic Facets, Directory Search/Sort & Mobile Ergonomics**: Dynamic context-preserving Facet Workbench (`AUD-007`), Rankings Directory search/sort/layout & `/authors` progressive preview (`AUD-008`), live filter-sheet badges & smart drop-up combobox (`AUD-009`), mobile header/search/clear-all/`60fps` tag fixes (`AUD-010`), and range/unmatched/comment-link/responsive polish (`AUD-013`).
- **M4 — Reproducible Post-Change Benchmarks, Adversarial Subagent Reviews & Release Readiness**: Re-run identical 200k benchmark harness, run independent `frontend-reviewer` and `arch-security-db-reviewer` subagents, resolve all findings, sync all user/ops docs, and pass every release check.

### Mid-Term (Future Self-Hosted Enhancements — Out of Scope Unless Requested)
- Optional incremental FTS background merge tuning (`usermerge`) for archives growing past `1,000,000+` items.
- Optional OPML/JSON export of saved search presets for power archivists (deliberately omitted now to keep zero user-account state).

### Explicit Non-Goals ("What We Deliberately Do NOT Do")
- **No microservice / Postgres / Redis / Elasticsearch / Meilisearch split**: Violates single-node low-cost self-hosting (`ADR-0002`).
- **No React / Next.js / SPA migration**: Breaks zero-JS progressive enhancement and strict buildless runtime simplicity (`ADR-0001`).
- **No bypassing upstream rate limits, `robots.txt`, CAPTCHAs, or age gates, and no local media hosting**: Violates legal/ethical boundaries and `ADR-0003`.

---

## 2. Detailed Milestone Execution Plan (`EXECPLAN`)

### Milestone 0 — Engineering Memory & Repository Cleanup
- **Files**: `docs/evolution/*.md`, `docs/adr/*.md`, remove `design-evidence/**`, `DESIGN_CONTRACT.md`, `DESIGN_PROGRESS.md`, `DESIGN_REVIEW.md`, `DESIGN_ROADMAP.md`.
- **Verification**: `git status`, verify no tests/scripts reference deleted scratch artifacts.

### Milestone 1 — Storage Schema v5, Search Correctness & Query Performance
- **Files**:
  - `search_iwara/storage/connection.py`: Add `contentless_delete_supported()` (`sqlite >= 3.43.0`) and `PRAGMA journal_size_limit = 67108864`.
  - `search_iwara/storage/sql.py`: Fix `HOT_SCORE_UPDATE` & `HOT_SCORE_UPDATE_RECENT` to use JST (`datetime('now', '+9 hours')`, `date('now', '+9 hours', '-30 days')`); add `ACTIVE_MOVIE_COUNT_REFRESH` (`app_meta['active_movies']`).
  - `search_iwara/storage/search_index.py`: Stream batch indexing (`fetchmany(5_000)`), enforce `m.status = 'active'` on `index_movie()` and full rebuilds, add `fts_table_ddl()`, `rebuild_all_indexes()`, `optimize_indexes()`, and `verify_indexes()`.
  - `search_iwara/storage/migrations.py`: Add `_v5_compact_fts_author_index_and_counts` creating `idx_movies_author_top(author_id, status, popularity DESC, source_site_id DESC)`, rebuilding `movie_search` & `movie_search_short` with `content='', contentless_delete=1` (+ `detail=none` on `movie_search_short` when supported) over `status = 'active'` rows only, refreshing JST `hot_score` and `app_meta['active_movies']`.
  - `search_iwara/storage/crawl_store.py`: Purge FTS in `mark_movie_missing()`; reindex linked active movies when `_upsert_entity()` detects an entity rename; preserve `status = 'suppressed'` across `upsert_list_items`, `missing_or_stale_detail_ids`, `stale_detail_ids` (using JST `SOURCE_TZ`), and `apply_movie_detail`; add `suppress_movies()`, `unsuppress_movies()`, and FTS `'optimize'` + `active_movies` refresh in `refresh_derived()`.
  - `search_iwara/storage/search_store.py`: Cardinality-ordered `mode == 'all'` (`MIN(movie_count)` driving subquery + PK `EXISTS`), single-pass page-1 `search()` when `< page_size`, NFKC `clean_text()` in `autocomplete_with_counts()` & `resolve_entity_names()`, `facet_counts(filters, limit=5)` over bounded matching set (`LIMIT 2000`), and optimized `related_movies()` (`MATERIALIZED` + `CROSS JOIN`, works on `missing` source movies, `with_tags=True`, `0` full-table scans, `suppressed` excluded from `get_movie()`).
  - `search_iwara/storage/ranking_store.py`: Optimize `top_movies_by_author()` via correlated `LIMIT ?` index scan on `idx_movies_author_top`; add `q` + `sort` (`popularity`, `hot`, `movies`, `favorites`, `views`) to `count()` & `top()`; read `active_movies` from `app_meta` in `dataset_status()`; remove dead `sidebar()`.
  - `search_iwara/cli.py`: Add `db suppress`, `db unsuppress`, and `db reindex` (`--verify`).
- **Verification**: Unit + upgrade migration tests (`v1`→`v5`, `v4`→`v5`), Hypothesis Search Oracle Equivalence tests (`tests/test_properties.py`), `pytest -m slow`.

### Milestone 2 — Crawler Safety, Web HTTP Semantics & Deployment Hardening
- **Files**:
  - `search_iwara/crawler.py`: `follow_redirects=False`, validated `<= 5`-hop redirect loop (scheme + host allow-list + `_check_robots`), streaming byte ceiling (`2 MiB` robots, `10 MiB` HTML).
  - `search_iwara/web/{pages,ops,api,security,app,context,query}.py`: Run canonical `303` redirects (blank params, `q_*` resolution, inverted range swap) before ETag `304`; persist `LANG_COOKIE` on `304` when `?lang=` is explicit; catch `StorageError` in `/readyz` (`503`); support `HEAD` on `/robots.txt`, `/favicon.ico`, `/sitemap*.xml`, `/metrics`, `/api/{kind}`; add `COOP: same-origin` & `CORP: same-origin`; populate `dataset` safely on non-500 error pages; remove dead `context.sidebar()`.
  - `deploy/docker/{sync-loop.sh,backup-loop.sh}`, `deploy/linux/nginx/*`, `deploy/linux/run-alert.sh`, `deploy/linux/search_iwara_deploy/config.py`: Immediate first sync + `SIGTERM` trap/wait, Nginx `/static/` security headers + `?v=`-scoped `immutable`, webhook scheme/host validation.
- **Verification**: `pytest tests/test_crawler.py tests/test_web.py tests/deploy`, `shellcheck`.

### Milestone 3 — Frontend UX, Dynamic Facets, Directory Search/Sort & Mobile Ergonomics
- **Files**:
  - `search_iwara/locales/{zh-Hans,ja,en}.toml`: Trilingual keys for dynamic facets, directory search/sort, author works toggle, unmatched entity chips, and pending detail badge (100% key parity).
  - `search_iwara/web/pages.py`, `search_iwara/web/formatting.py`: Dynamic context-preserving `workbench` builder, directory `?q=` & `?sort=` handler, `linkify_comment` safe Jinja filter, isolated `q_*` `remove_href`, unmatched chip metadata.
  - `search_iwara/templates/{base,index,_macros,movie_detail,entity_index}.html`: Top nav `Search` + 4 core dimensions, desktop single-bar directory header with search + sort controls, collapsible `<details>` author rails (`#1..#3` open on page 1), `Date & metrics` badge hook, mobile accessible "Clear all", compact mobile taxonomy.
  - `search_iwara/static/{app.js,style.css,manifest.webmanifest}`: Live 5-group `<summary>` count badges, `.is-dropup` combobox positioning without instant scroll jump, unconfirmed combobox text handling, mobile `.brand` icon + roomy search input (`>= 16px` font, hidden `.search__scope`) + `.tag__text` truncation fix, tightened directory table layout, smooth `768–1100px` toolbar, `.no-js` kbd hide, updated manifest colors.
- **Verification**: `tsc -p jsconfig.json`, `pytest tests/test_web.py`, `pytest -m e2e` (`axe-core` WCAG 2.2 AA).

### Milestone 4 — Benchmarks, Independent Adversarial Reviews, Docs & Final Verification
- **Files**: `docs/evolution/{BENCHMARKS,PROGRESS}.md`, `README.md`, `README.zh-CN.md`, `SECURITY.md`, `DESIGN.md`, `CHANGELOG.md`, `docs/*.md`, `docs/assets/screenshots/*.jpg`.
- **Verification**: Full 200k `after_metrics.json` comparison, independent `frontend-reviewer` + `arch-security-db-reviewer` subagents, all CI & Docker & Prometheus gates green.
