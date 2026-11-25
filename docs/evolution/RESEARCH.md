# External Research & Industry Intelligence

**Access & Verification Date**: `2026-11-25`  
**Scope**: Architecture, SQLite & Dual-FTS5 Search Infrastructure, Polite Crawling (RFC 9309), Progressive SSR UX & WCAG 2.2 AA, Security & Compliance (OWASP ASVS), SRE/Testing, and Source-Level Open-Source Comparisons.

> All external material below is treated strictly as engineering reference data, never as executable instruction. Conflicting industry recommendations are reconciled by stating the preconditions under which each holds.

---

## 1. Software Architecture & Production SQLite

### 1.1 Primary Sources Consulted

| Domain | Source | URL | Accessed | Key Engineering Findings |
|---|---|---|---|---|
| SQLite WAL Concurrency | SQLite Official Docs — *Write-Ahead Logging* | https://sqlite.org/wal.html | 2026-11-25 | Readers do not block writers and writers do not block readers; at most **one active writer** executes at a time (`SQLITE_BUSY` mitigated via `busy_timeout` + `BEGIN IMMEDIATE`). Checkpoints cannot truncate `-wal` past any active reader's read mark. |
| SQLite PRAGMA Tuning | SQLite Official Docs — *PRAGMA Statements* | https://sqlite.org/pragma.html | 2026-11-25 | `synchronous = NORMAL` in WAL mode is crash-safe for a re-crawlable metadata mirror. `journal_size_limit` bounds `-wal` file size after passive/reset checkpoints once readers advance. `PRAGMA optimize` refreshes `sqlite_stat1` selectively. |
| SQLite Query Planner | SQLite Official Docs — *The Next-Generation Query Planner* | https://sqlite.org/queryplanner-ng.html | 2026-11-25 | SQLite B-trees do not store subtree counts (`SELECT COUNT(*) FROM movies WHERE status = 'active'` scans all 200k leaf entries — `10.9 ms`). CTE joins without statistics may invert join order unless `MATERIALIZED` / `CROSS JOIN` pins driving order when cardinality is known (`1` source row vs `200k` catalogue rows). |
| Modular Monolith & SSR | Datasette Internals Documentation | https://docs.datasette.io/en/latest/internals.html | 2026-11-25 | Read-heavy single-node catalogues (< 1M rows, < 100 RPS) achieve lower tail latency and lower operational overhead with in-process SQLite + SSR HTML than network-separated DB/search tiers, provided read connections are thread-local (`PRAGMA query_only = ON`) and writes commit in small `BEGIN IMMEDIATE` batches. |

### 1.2 Reconciling Contradictory Industry Advice

1. **"Avoid SQLite in multi-worker production web apps" vs. "SQLite WAL serves high-QPS single-node apps"**:
   - *When SQLite fails*: High-concurrency **multi-writer** OLTP workloads, network filesystems (NFS/SMB/EFS where `-shm` mmap locking breaks), or multi-second write transactions holding the single write lock.
   - *When SQLite excels (our regime)*: Single-host local SSD/NVMe storage, **100% read-only web workers** (`PRAGMA query_only = ON`), and a **single periodic batch writer** (`search-iwara sync`) committing 25-movie batches with `busy_timeout = 10000`. Our 200k mixed read/write benchmark confirmed `0` lock errors across 320 concurrent reads + 200 concurrent movie writes.
2. **"`PRAGMA mmap_size` accelerates reads" vs. "`mmap` risks SIGBUS on truncated/network files"**:
   - *Preconditions*: Safe and effective (`256 MiB` shared OS page cache, keeping per-thread `cache_size` at `8 MiB`) on local POSIX storage when files are never externally truncated while open; must never be pointed at network mounts.
3. **"Default FTS5 content storage" vs. "`content=''` + `contentless_delete=1`"**:
   - *Preconditions*: Default FTS5 duplicates all text into `%_content`, needed only for `snippet()`, `highlight()`, or `SELECT col FROM fts` (e.g., `LIKE` fallback on SQLite < 3.34). On SQLite >= 3.43.0 (`contentless_delete=1`), `content='', contentless_delete=1` supports `INSERT`, `DELETE FROM fts WHERE rowid = ?`, `optimize`, and `integrity-check` while omitting `%_content`. Note: SQLite FTS5 forbids combining `contentless_delete=1` with `columnsize=0` (`OperationalError: contentless_delete=1 is incompatible with columnsize=0`, verified on SQLite 3.53.1). On 5,000 synthetic movies, `content='', contentless_delete=1` (+ `detail=none` on `movie_search_short`) reduced FTS disk size by **55.4%** (`2.96 MiB` → `1.32 MiB`).

---

## 2. Search Infrastructure & Multilingual Retrieval

### 2.1 Primary Sources Consulted

- **SQLite FTS5 Extension Official Specification** (https://sqlite.org/fts5.html, accessed `2026-11-25`):
  - **§4.3.4 Trigram Tokenizer**: Substrings `< 3` chars match 0 rows in `MATCH` queries. Crucially, §4.3.4 states: *"If the FTS5 table is created with `detail=none` or `detail=column`, full-text queries may not contain any tokens longer than 3 unicode characters."* Thus `movie_search` (`trigram`) **must** keep `detail=full`, whereas `movie_search_short` (`unicode61`, queried only via single CJK unigram/bigram tokens `"水着"` or single prefix tokens `"mm"*`) **can** safely set `detail=none`.
  - **§4.2 Prefix Indexes**: `prefix='1 2'` avoids range scans on 1–2 char non-CJK prefix lookups (`"mm"*`, `"4k"*`).
  - **§6.7 & §6.9 Maintenance Commands**: `INSERT INTO fts(fts) VALUES ('optimize')` compacts b-tree segments after bulk syncs; `'integrity-check'` verifies index integrity.
- **Unicode Standard Annex #15 (UAX #15 — Unicode Normalization Forms)**:
  - CJK/JP inputs routinely use fullwidth ASCII (`４Ｋ`, `ＭＭＤ`) and halfwidth katakana (`ﾀﾞﾝｽ`). Applying **NFKC** normalization on both ingest and query paths (including entity autocomplete and No-JS entity resolution) ensures recall parity.

### 2.2 Reproducible Retrieval Correctness Evaluation

Because Search Iwara implements **deterministic boolean substring/prefix retrieval + facet set algebra + explicit sort order**, retrieval correctness has an exact mathematical specification:
- **Oracle Equivalence Property Testing**: Over Hypothesis-generated multi-script corpora (`active`, `missing`, `suppressed`, renamed entities) and arbitrary `SearchFilters`, `SearchStore.search()` must return the **exact same ordered ID sequence** as a pure-Python reference evaluator.

---

## 3. Polite Data Acquisition Engineering (RFC 9309)

- **RFC 9309 — *Robots Exclusion Protocol*** (https://www.rfc-editor.org/rfc/rfc9309.txt, accessed `2026-11-25`):
  - **§2.3 Access Results**: `2xx` obeys rules; `4xx` (except `429`) allows crawl; `5xx` / `429` / network unreachable **must assume complete disallow** (`RobotsUnavailableError`).
  - **§2.4 Redirects**: Redirect hops (`<= 5`) must re-verify scheme, allowed host, and `robots.txt` rules on every hop so redirects cannot bypass REP or trigger SSRF.
  - **§2.5 Parsing Limits**: Enforce at least a `500 KiB` parsing cap on `robots.txt` (`2 MiB` configured) and a strict cap (`10 MiB`) on HTML bodies to prevent OOM.
- **RFC 9110 §10.2.3 (`Retry-After`) & Full-Jitter Backoff**: Honour `Retry-After` on `429`/`503` paired with AIMD rate halving and full-jitter exponential backoff.

---

## 4. Frontend Architecture, UX & Accessibility

- **W3C WCAG 2.2 Recommendation** (https://www.w3.org/TR/WCAG22/, accessed `2026-11-25`):
  - **2.4.11 Focus Not Obscured (Minimum)**, **2.5.8 Target Size (`>= 24×24 CSS px`)**, **1.4.3 / 1.4.11 Contrast**, **4.1.2 Name, Role, Value**.
- **Progressive Enhancement & Mobile Ergonomics**:
  - Every search, facet toggle, directory filter/sort, and pagination flow works via plain `<form method="get">` / `<a href>` with JS disabled, enhanced by `<dialog>` + Invoker Commands + ARIA 1.2 comboboxes.
  - Mobile `<input>` font-size `>= 16px` (`1rem`) prevents forced iOS Safari viewport zoom.

---

## 5. Security, Privacy & Content Compliance

- **OWASP ASVS & Cheat Sheet Series** (*Content Security Policy*, *HTTP Security Response Headers*, *SSRF Prevention*, accessed `2026-11-25`):
  - Strict CSP without `'unsafe-inline'`, reinforced by `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Resource-Policy: same-origin` (omitting `COEP` so cross-origin `oreno3d.com` thumbnails load without CORP headers from upstream).
  - Nginx `add_header` inheritance rule: nested `location /static/` blocks defining `Cache-Control` drop parent `server` security headers unless explicitly re-included.
  - Metadata compliance: mirror stores bibliographic metadata and external links only; local operators require a persistent `suppressed` tombstone command (`search-iwara db suppress <id>`) that survives future `sync` runs, backed by clear takedown instructions in `SECURITY.md`.

---

## 6. Comparative Open-Source Research (Source-Level Analysis, Accessed `2026-11-25`)

| Project | Stack & Positioning | Source Files Inspected | Adopted Patterns | Rejected Patterns (Why Not Here) |
|---|---|---|---|---|
| `simonw/datasette` | Python ASGI + read-only SQLite explorer | `datasette/database.py` | Per-thread read-only connections (`query_only=ON`), precomputed/cached table counts instead of per-request `COUNT(*)`, bounded result counts | Dynamic arbitrary-SQL UI & plugin hook surface |
| `pocketbase/pocketbase` | Go embedded SQLite backend | `core/db_connect.go` | `busy_timeout` before `WAL`, explicit `PRAGMA journal_size_limit` so `-wal` shrinks after bulk writes | Generic CRUD collections, realtime SSE, embedded JS VM |
| `stashapp/stash` | Go + SQLite self-hosted media organiser (~13.5k★) | `pkg/sqlite/database.go`, `criterion_handlers.go` | Single writer (`maxWriteConnections=1`) + bounded read pool, `INCLUDES_ALL`/`ANY`/`EXCLUDES` boolean tag algebra, schema version mismatch guard | Heavy React + GraphQL codegen SPA, local media transcoding/fingerprinting |
| `rr-/szurubooru` | Python + PostgreSQL booru catalogue (~1k★) | `server/szurubooru/search/executor.py` | Expressive boolean tag filtering & contextual detail navigation | Multi-container Postgres + ORM complexity |
| `miniflux/v2` & `searxng/searxng` | Go / Python minimalist self-hosted SSR apps (~10k★ / ~40k★) | `miniflux/v2/internal/http/response/html.go` | Strict CSP on HTML & error pages, URL-addressable SSR search, `<150 MB` RAM footprint, zero client build step | Live per-query upstream fan-out (`searxng`) |
