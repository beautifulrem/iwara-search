# Configuration

Search Iwara reads configuration from `SEARCH_IWARA_*` environment variables (and any `.env` file in the working directory), validates all values at startup, and lets CLI flags override matching settings. Invalid values terminate startup with exit code `78` and report the offending field. Empty environment variables are treated as unset.

## Storage & Backups

| Variable | Default | CLI Flag | Description |
|---|---|---|---|
| `SEARCH_IWARA_DB` | `data/oreno3d.sqlite3` inside a git checkout; otherwise the OS user data directory (`~/.local/share/search-iwara/` on Linux, `~/Library/Application Support/search-iwara/` on macOS, `%LOCALAPPDATA%\search-iwara\` on Windows) | `--db-path` | Path to the SQLite database file (`SEARCH_IWARA_DB_PATH` alias also accepted) |
| `SEARCH_IWARA_BACKUP_DIR` | `<db_dir>/backups` | `db backup --dest` | Output directory for `search-iwara db backup` |
| `SEARCH_IWARA_BACKUP_KEEP` | `7` | `db backup --keep` | Number of backup snapshots retained after rotation |
| `SEARCH_IWARA_BACKUP_COMPRESS` | `false` | `db backup --compress` | Compress backups as `.sqlite3.gz` after `PRAGMA quick_check` |

## Web Server

| Variable | Default | CLI Flag | Description |
|---|---|---|---|
| `SEARCH_IWARA_HOST` | `127.0.0.1` | `serve --host` | Listen address |
| `SEARCH_IWARA_PORT` | `8000` | `serve --port` | Listen port |
| `SEARCH_IWARA_PAGE_SIZE` | `36` | | Results per page (`1`–`200`) |
| `SEARCH_IWARA_MAX_RESULT_WINDOW` | `10000` | | Maximum rows counted and paginated per search; larger result sets display as `10,000+` |
| `SEARCH_IWARA_WEB_THREADS` | `16` | | Request worker threads; each thread holds one read-only SQLite connection |
| `SEARCH_IWARA_METRICS_ENABLED` | `true` | | Enable the Prometheus `/metrics` endpoint |
| `SEARCH_IWARA_METRICS_TOKEN` | unset | | Optional bearer token (`16`–`256` chars of `[A-Za-z0-9_-]`) for `/metrics`; when unset, `/metrics` only answers loopback requests |
| `SEARCH_IWARA_API_DOCS_ENABLED` | `false` | | Expose Swagger UI at `/api/docs` and OpenAPI JSON at `/api/openapi.json` |
| `SEARCH_IWARA_ALLOW_INDEXING` | `false` | | When `false`, `robots.txt` disallows all crawlers and pages emit `noindex`; when `true`, `/sitemap.xml` is enabled |
| *(CLI only)* | `true` | `serve --proxy-headers / --no-proxy-headers` | Honour `X-Forwarded-*` headers from trusted proxies |
| *(CLI only)* | `127.0.0.1` | `serve --forwarded-allow-ips` | Proxy IPs trusted for `X-Forwarded-*` |
| *(CLI only)* | `false` | `serve --reload` | Auto-reload on code/template edits (development only) |

## Crawler & Sync

| Variable | Default | CLI Flag | Description |
|---|---|---|---|
| `SEARCH_IWARA_REQUEST_CONCURRENCY` | `4` | `--request-concurrency` | Maximum concurrent HTTP requests and detail workers (`1`–`64`) |
| `SEARCH_IWARA_REQUEST_RATE` | `2.0` | `--request-rate` | Ceiling in requests/second; halves automatically on `429`/`503` |
| `SEARCH_IWARA_LIST_PREFETCH_PAGES` | `4` | `sync full --list-prefetch-pages` | Listing pages fetched per batch during `sync full` |
| `SEARCH_IWARA_REQUEST_TIMEOUT_SECONDS` | `30` | | Per-request HTTP timeout in seconds |
| `SEARCH_IWARA_REQUEST_RETRIES` | `4` | | Retry count on `408`, `425`, `429`, `5xx`, timeouts, and transport errors |
| `SEARCH_IWARA_BACKOFF_BASE_SECONDS` | `1.0` | | Base delay for full-jitter exponential backoff |
| `SEARCH_IWARA_BACKOFF_MAX_SECONDS` | `60` | | Backoff ceiling; `Retry-After` greater than `5x` this skips the URL for the current run |
| `SEARCH_IWARA_RESPECT_ROBOTS` | `true` | | Enforce `robots.txt` rules and `Crawl-delay` |
| `SEARCH_IWARA_USER_AGENT` | `search-iwara/<version> (+repo URL)` | | Outbound HTTP `User-Agent` |
| `SEARCH_IWARA_PROXY` | unset | | Explicit proxy URL (`socks5://127.0.0.1:1080`, `http://proxy:3128`) |
| `SEARCH_IWARA_TRUST_ENV` | `true` | | Read `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and `NO_PROXY` from process env |
| `SEARCH_IWARA_HTTP2` | `true` | | Enable HTTP/2 negotiation |
| `SEARCH_IWARA_DETAIL_MAX_ATTEMPTS` | `6` | | Maximum automatic retry attempts for a failing movie detail page |
| `SEARCH_IWARA_DETAIL_REFRESH_WINDOW_DAYS` | `30` | | Refresh details of movies published within this many days... |
| `SEARCH_IWARA_DETAIL_REFRESH_AFTER_HOURS` | `72` | | ...once their stored detail record is older than this many hours |
| `SEARCH_IWARA_DETAIL_REFRESH_LIMIT` | `500` | | Maximum stale detail refreshes queued per `sync latest` run |
| `SEARCH_IWARA_RESUME_OVERLAP_PAGES` | `1` | | Pages re-checked behind the saved checkpoint when `sync full` resumes |
| `SEARCH_IWARA_SYNC_FAILURE_TOLERANCE` | `10` | | Failed detail fetches tolerated before `sync` exits `1` (any failed listing page exits `1`) |
| *(CLI only)* | `3` | `sync latest --stable-pages` | Consecutive pages without unseen movie IDs before `sync latest` stops |
| *(CLI only)* | unset | `--max-pages`, `sync full --start-page` | Cap scanned pages or override the starting page |

Built-in network bounds enforced regardless of configuration: HTTP redirects are capped at 5 validated hops within the configured `https` origin (checking `robots.txt` on every hop), and streaming response reads abort above `2 MiB` (`robots.txt`) or `10 MiB` (HTML pages).

## Logging

| Variable | Default | Description |
|---|---|---|
| `SEARCH_IWARA_LOG_FORMAT` | `auto` | `text`, `json`, or `auto` (`text` on interactive TTYs, `json` otherwise) |
| `SEARCH_IWARA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

## Database Maintenance CLI

| Command | Description |
|---|---|
| `search-iwara db migrate` | Apply ordered schema migrations up to Schema v5 |
| `search-iwara db backup [--dest DIR] [--keep N] [--compress]` | Online SQLite backup, `PRAGMA quick_check`, disk-headroom guard, optional gzip compression, and rotation |
| `search-iwara db refresh` | Recompute `entity_stats`, JST `hot_score`, and FTS segment compaction |
| `search-iwara db reindex [--verify]` | Stream-rebuild FTS5 indexes in 5,000-row batches, or `--verify` active-movie index parity (exits `1` on mismatch) |
| `search-iwara db suppress <id...> [--reason TEXT]` | Hide `source_site_id` entries across search, detail pages, APIs, rankings, and sitemaps (`status='suppressed'`) |
| `search-iwara db unsuppress <id...>` | Restore suppressed `source_site_id` entries back to `status='active'` and reindex |

## Process Exit Codes

| Code | Meaning |
|---|---|
| `0` | Completed normally |
| `1` | Listing page failure, detail failures above `SEARCH_IWARA_SYNC_FAILURE_TOLERANCE`, index parity mismatch, or unreachable `robots.txt` (RFC 9309) |
| `2` | Parser drift detected: upstream HTML structure changed; sync aborted before writing bad records |
| `75` | Another sync process holds `<db>.sync.lock` (`EX_TEMPFAIL`; treated as clean skip by `systemd`) |
| `78` | Invalid configuration (`EX_CONFIG`) |
| `143` | Stopped by `SIGTERM` or `SIGINT`; committed batches remain intact and the run is marked `failed` |

Deployment-specific variables (`SEARCH_IWARA_SYNC_HOURS`, `SEARCH_IWARA_ALERT_WEBHOOK`, `SEARCH_IWARA_IMAGE`, etc.) are documented in [docs/linux-deploy.md](linux-deploy.md).
