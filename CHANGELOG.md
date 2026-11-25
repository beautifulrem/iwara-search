# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security & Compliance
- **Takedown tombstones (`db suppress` / `db unsuppress`)**: Operators can suppress movie ids via
  `search-iwara db suppress <id...> [--reason TEXT]` (`status='suppressed'`). Suppressed movies are
  removed from FTS5, `entity_stats`, `/movies/{id}`, `related_movies`, `/api/*` and sitemaps, and
  remain suppressed if re-listed upstream during `sync latest` / `sync full`.
- **Crawler SSRF, redirect & body guards**: `Oreno3dClient` disables implicit redirects and manually
  validates up to 5 redirect hops against `https` + the configured upstream origin and per-hop
  `robots.txt` rules, while streaming response bodies with strict caps (`2 MiB` for `robots.txt`,
  `10 MiB` for HTML pages).
- **Deployment hardening**: Validated `alert_webhook` against private/loopback/link-local SSRF in
  non-interactive Linux deploy configs; added full security headers (`CSP`, `CORP`, `X-Frame-Options`,
  `X-Content-Type-Options`) and fingerprinted immutable cache maps to nginx `/static/` locations;
  added immediate initial sync and `SIGTERM`/`SIGINT` child forwarding to Docker loop scripts.

### Storage & Performance
- **Schema v5 compact FTS5 (`contentless_delete=1`)**: Converted `movie_search` and
  `movie_search_short` (`detail=none`) to contentless-delete FTS5 tables indexing only `active`
  movies and rebuilt via streamed `fetchmany(5_000)` batches. On a 200k-movie database, peak
  migration RSS dropped **4.5×** (`2,705 MB` → `597 MB`), database size shrank **29.3 %**
  (`327.4 MB` → `231.4 MB`), and online backups ran **2.0×** faster.
- **Query-plan & concurrency wins**:
  - `tag_all` now seeds from the rarest tag via `entity_stats` and probes remaining tags via PK
    `EXISTS` (`261.3 ms` → `90.3 ms` P50; 16-thread concurrent read throughput `+68.9 %`).
  - `related_movies` uses `MATERIALIZED` CTEs + `CROSS JOIN` (`41.1 ms` → `8.9 ms` P50), works even
    when the viewed movie is `missing`, and batches card tags.
  - Added `idx_movies_author_top` (`GET /authors` P95 `-36.8 %`), ACID `app_meta['active_movies']`
    status triggers (`dataset_status` `518×` faster), `PRAGMA journal_size_limit = 64 MiB`, bounded
    FTS `merge(64)` maintenance, and deferred `fts_dirty` rebuilds when mega-entities (> 500 movies)
    are renamed.
- **Correctness**: Fixed JST (`+9 hours`) vs UTC 9-hour skew in `hot_score` and stale-detail
  windows; normalized entity lookups with Unicode NFKC; maintained FTS5 consistency across entity
  renames and `missing`/`suppressed` transitions; added `search-iwara db reindex [--verify]` and a
  200-example Hypothesis Search Oracle property test.

### Web & HTTP Semantics
- Fixed `GET /?lang=...` + `If-None-Match` (`304`) dropping the `Set-Cookie: ui_lang` header.
- Canonical `303` query redirects and inverted-range auto-swaps now execute before `ETag` checks.
- Added `HEAD` support across `/healthz`, `/readyz`, `/metrics`, `/robots.txt` and `/api/{kind}`;
  `/readyz` cleanly catches `StorageError` and returns `503`.

### UI & Accessibility
- **Dynamic result-scoped Facet Workbench**: Sidebar facets on `/` recompute live counts against the
  active search/filter result set (exact up to 2 000 matches, bounded 2 000-row sample above, while
  preserving sibling union candidates on `ANY` dimensions) and preserve existing query parameters on
  click.
- **Searchable, multi-sort directories**: `/characters`, `/authors`, `/tags` and `/categories`
  support `?q=` filtering and 5 sort modes (`hot`, `popularity`, `count`, `favorites`, `views`),
  with progressive `<details>` work-sample disclosure on `/authors`.
- **Filter & mobile ergonomics**: Live badge updates across all 5 filter `<details>` groups,
  viewport-aware `.is-dropup` combobox popups, visible mobile brand identity, on-screen mobile
  `Clear all filters`, `≥ 16 px` coarse-pointer inputs, un-clipped `60fps` badges, pending-detail
  status notice, and safe `https://` linkification in author notes with screen-reader hints.

## [0.2.2] — 2026-10-01

### Fixed
- Deployment without a domain (nginx `server_name _`) on Debian/Ubuntu: the distribution's
  "Welcome to nginx" default site shadowed Search Iwara when visiting the server's IP. The site is
  now the `default_server` in catch-all mode and the stock default site link is disabled (the file
  is kept; restored automatically if `nginx -t` fails). Found on the first real-server install.

## [0.2.1] — 2026-10-01

### Security
- Upgrade dependencies with published advisories found by the CI audit: starlette 1.0.0 → 1.7.0
  (PYSEC-2026-161, -248, -249, -2280, -2281, via fastapi 0.135 → 0.142), anyio 4.13 → 4.14.2
  (CVE-2026-63374, CVE-2026-64847), click 8.3.2 → 8.5.0 (PYSEC-2026-2132) and idna 3.11 → 3.20
  (PYSEC-2026-215); typer 0.24 → 0.27 for click 8.5 compatibility.

### Fixed
- CI dependency audit: audit the locked runtime requirements under Python 3.13 without
  re-resolving (it previously failed before checking anything).
- Tests use `httpx2` for Starlette's test client, as Starlette 1.7 recommends.

## [0.2.0] — 2026-10-01

### Security
- Scraped URLs are allow-listed (https + oreno3d.com / iwara.tv) at parse time, sanitised in
  existing databases by migration, and filtered again at render time. Fixes a stored XSS via
  `javascript:` links.
- Strict Content-Security-Policy and security headers on every response; no inline scripts or styles.
- Input limits on every query parameter; oversized or malformed requests get a 422 page instead of a 500.
- Hardened systemd units, dedicated system user, TLS 1.2+/HSTS nginx templates, rate limiting.

### Crawler
- Polite defaults: 4 concurrent requests, 2 req/s token bucket, honest User-Agent, robots.txt and `Crawl-delay`.
- Error classification, full-jitter exponential backoff, `Retry-After`, adaptive (AIMD) throttling on 429/503.
- SOCKS/HTTP proxies work out of the box (`httpx[socks,http2]`), plus `SEARCH_IWARA_PROXY` / `SEARCH_IWARA_TRUST_ENV`.
- Listing scan and detail fetching run as a pipeline with group commits; per-page failure isolation.
- Parser-drift detection (exit code 2), capped and spaced retries for failed details, TTL refresh of recent details,
  `sync latest` stability based on new ids only, `sync full` resume with overlap, a sync lock (exit code 75).

### Search & performance
- Trigram FTS5 over title, author, character, origin and tag names (CJK substring search).
- Materialised ranking read model, composite indexes, capped counting, read-only connection pool:
  the sidebar went from 4.4 s to < 1 ms and default search from 350 ms to < 1 ms on 200k movies.
- Related movies computed in a single weighted CTE with IDF-style fan-out caps.

### UI
- Redesigned interface: OKLCH design tokens, light/dark/system themes, container queries, view transitions.
- Filter dialog with ARIA combobox autocomplete, active-filter chips, full sort menu, English locale,
  Accept-Language negotiation; built to WCAG 2.2 AA and checked with axe (see docs/accessibility.md).

### Brand & docs
- New logo: a magnifier with a faceted-diamond lens and a play glyph (original mark), shipped as SVG
  favicon plus PNG/maskable PWA icons and an Apple touch icon; regenerated by `scripts/make_brand_assets.py`.
- README rewritten (hero, highlights, screenshots, quick start, collapsible reference) in English and
  Chinese; screenshots come from a work-safe demo catalogue via `scripts/make_screenshots.py`.

### Operations
- `search-iwara db migrate|backup|refresh`; versioned migrations; JSON logs; `/healthz`, `/readyz`, `/metrics`.
- Docker image and compose file; backup timer; failure alerts; `manage.py update`.
- CI with lint, strict typing, coverage gate, performance budgets, browser E2E + axe, dependency audit.

### Hardening (review round 3)
- Only ASCII digits are accepted as ids/numbers (`²` no longer causes a 500); numeric parsing rejects `inf`/`1e999`.
- robots.txt handling follows RFC 9309 (4xx → allow, 5xx/429/unreachable → stop the run).
- SIGTERM/SIGINT end a sync gracefully (exit 143); orphaned `running` records are closed.
- Short queries are index lookups too: CJK n-grams and Latin word prefixes; stable tie-breakers for count sorts.
- Weak ETags and 304s for HTML, bounded worker threads, sitemaps, per-language canonical URLs.
- `/metrics` is loopback-only unless a Bearer token is configured; Swagger UI is opt-in.
- Crawler statistics per run in `sync_runs` and as Prometheus gauges; structured access log.
- Comments keep their line breaks; literal `\n` escapes from the source are decoded.
- Typed template contexts, shared row mappers, deployment manager split into a typed package.
- Property-based tests (Hypothesis), E2E in Chromium/Firefox/WebKit, coverage gate 95 %.

### Changed
- `--request-delay-ms` and `--detail-batch-size` were replaced by `--request-rate` and the worker pool size
  (`--request-concurrency`). Old deployment env files are migrated by `deploy/linux/manage.py`.

## [0.1.0]

- Initial release: Oreno3D metadata mirror with SQLite search and a FastAPI UI.
