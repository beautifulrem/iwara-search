# Changelog

All notable changes to Search Iwara are documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-11-25

### Added
- **Schema v5 & storage maintenance**: Compact `content='', contentless_delete=1` FTS5 tables (`detail=none` on `movie_search_short`, cutting 200k-movie DB size by ~29% and migration peak RSS by ~78%), trigger-maintained `app_meta['active_movies']`, and `search-iwara db reindex [--verify]`, `db suppress <id...>`, `db unsuppress <id...>`, and `db backup --compress` (`.sqlite3.gz` snapshots with `PRAGMA quick_check` and disk-headroom guards).
- **Dynamic facet sidebar & searchable directories**: `/` sidebar computes live result-scoped facet counts on filtered queries with one-click `+` (include) / `−` (exclude) operators and JST date/metric presets (`7d`, `30d`, `90d`, `Views >= 1K`, `Likes >= 100`). Entity directories (`/characters`, `/authors`, `/tags`, `/origins`, `/categories`) support `?q=` search and 5 sort orders.
- **No-JS entity resolution & autocomplete counts**: Inline filter forms resolve typed entity names (`q_*`) on the server with `303` redirects to canonical IDs, and `/api/{kind}?counts=1` exposes indexed work counts in combobox suggestions.
- **Automated release pipeline**: Tag-driven `.github/workflows/release.yml` and `scripts/release.py` (`make release VERSION=X.Y.Z`) publishing GitHub Releases, SLSA-attested Python wheels/sdists with `SHA256SUMS`, and native multi-arch (`linux/amd64`, `linux/arm64`) container images on `ghcr.io/beautifulrem/iwara-search`.
- **200k benchmark suite**: Deterministic synthetic benchmark harness (`scripts/bench_200k.py`) and documented results (`docs/benchmarks.md`).

### Changed
- Redesigned search, filter drawer, detail, directory, empty-database, and error pages around low-chroma slate surfaces, semantic boolean filter chips (`ALL` / `ANY` / `NOT`), `<main>`-before-`<aside>` keyboard tab order, and compact single-row mobile toolbars.
- Detail pages preserve active search/filter context across "Back to search" and `+`/`−` taxonomy pivots, safely linkify allow-listed URLs in author notes, and render upstream-removed entries (`status='missing'`) as archived records without active playback CTAs.
- Hardened `Oreno3dClient` with per-hop redirect validation (`<= 5` hops, `https` origin + `robots.txt` checked on every hop) and streaming response byte caps (`2 MiB` `robots.txt`, `10 MiB` HTML).
- Hardened operations: `systemd` `WatchdogSec=90s` + `OOMPolicy=kill`, cgroup-aware SQLite `mmap_size` scaling on low-RAM hosts, SSRF-checked failure webhooks, immediate startup sync + `SIGTERM` forwarding in Docker `sync-loop.sh`, `python:3.15-slim` runtime image, and prebuilt GHCR default image in `compose.yaml`.
- Migrated HTML parsing in `search_iwara/parsers.py` to `selectolax.lexbor` (`LexborHTMLParser`) and upgraded runtime/dev lockfile dependencies.

### Fixed
- Eliminated mid-character CJK glyph clipping on card tags and author names, showing `+N` overflow badges when a movie carries more than three tags.
- Fixed `304 Not Modified` / `HEAD` responses, WebKit coarse-pointer radio pill targets, WCAG 2.5.3 `label-content-name-mismatch` on the header language switcher, JST `+9h` alignment in `hot_score` decay, and deferred mega-entity FTS renames (`fts_dirty`).
- Optimized `tag_all` (cardinality-ordered PK `EXISTS`, `2.89x` faster) and `related_movies` (`MATERIALIZED` + `CROSS JOIN`, `4.62x` faster) on 200k-movie datasets.

## [0.2.2] - 2026-10-01

### Fixed
- Catch-all `nginx` deployments (`server_name _`) without a domain on Debian/Ubuntu now set `default_server` and disable the stock `/etc/nginx/sites-enabled/default` symlink (restoring it automatically if `nginx -t` fails), preventing the default welcome page from shadowing Search Iwara on IP visits.

## [0.2.1] - 2026-10-01

### Security
- Upgraded locked runtime dependencies to resolve published advisories: `starlette` `1.0.0` -> `1.7.0` (via `fastapi` `0.135` -> `0.142`), `anyio` `4.13` -> `4.14.2`, `click` `8.3.2` -> `8.5.0`, `idna` `3.11` -> `3.20`, and `typer` `0.24` -> `0.27`.

### Fixed
- CI dependency audit now exports and audits locked runtime requirements directly under Python 3.13 without re-resolving.
- Switched Starlette test-client dependency to `httpx2`.

## [0.2.0] - 2026-10-01

### Added
- Dual FTS5 search index (`trigram` + CJK unigram/bigram `unicode61`), materialised `entity_stats` rankings, weighted related-video recommendations, read-only SQLite connection pool, and weak `ETag` / `304` responses.
- Polite `Oreno3dClient` with RFC 9309 `robots.txt` handling, AIMD rate limiting on `429`/`503`, jittered exponential backoff with `Retry-After`, HTTP/SOCKS5 proxy support, batched detail pipeline, parser-drift detection (exit code `2`), and `flock` run locking (exit code `75`).
- `search-iwara db migrate|backup|refresh` CLI commands, JSON structured logging, `/healthz` + `/readyz` + `/metrics` endpoints, Prometheus alert rules, hardened `systemd` + `nginx` deployment manager (`deploy/linux/manage.py`), and multi-stage `Dockerfile` + `compose.yaml`.
- Trilingual UI (`zh-Hans`, `ja`, `en`), WAI-ARIA 1.2 comboboxes, strict `Content-Security-Policy`, and `axe-core` WCAG 2.2 AA test suites.

### Security
- Enforced `https` host allow-listing (`oreno3d.com`, `iwara.tv`) at parse time, via database migration, and at template render time, closing stored XSS vectors from scraped links.
- Added structural bounds on all query parameters (`422` response on oversized input).

## [0.1.0]

- Initial release: local Oreno3D metadata mirror with SQLite search and FastAPI web UI.
