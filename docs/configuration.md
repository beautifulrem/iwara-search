# Configuration

All settings are read from `SEARCH_IWARA_*` environment variables (or a `.env` file in the
working directory), validated at start-up, and can be overridden by CLI options where one
exists. Invalid values stop the process with exit code 78 and a message naming the field.
Empty values are treated as "unset".

## Storage

| Variable | Default | CLI | Description |
|---|---|---|---|
| `SEARCH_IWARA_DB` | `data/oreno3d.sqlite3` in a source checkout; otherwise the per-user data dir (`~/.local/share/search-iwara/` on Linux, `~/Library/Application Support/search-iwara/` on macOS, `%LOCALAPPDATA%\search-iwara\` on Windows) | `--db-path` | SQLite database file |
| `SEARCH_IWARA_BACKUP_DIR` | `<db dir>/backups` | `db backup --dest` | Where `db backup` writes |
| `SEARCH_IWARA_BACKUP_KEEP` | `7` | `db backup --keep` | Backups kept after rotation |

## Web

| Variable | Default | CLI | Description |
|---|---|---|---|
| `SEARCH_IWARA_HOST` | `127.0.0.1` | `serve --host` | Bind address |
| `SEARCH_IWARA_PORT` | `8000` | `serve --port` | Bind port |
| `SEARCH_IWARA_PAGE_SIZE` | `36` | | Results per page (1–200) |
| `SEARCH_IWARA_MAX_RESULT_WINDOW` | `10000` | | Results counted/paginated per query; larger totals show as "10,000+" |
| `SEARCH_IWARA_METRICS_ENABLED` | `true` | | Expose `/metrics` |
| `SEARCH_IWARA_METRICS_TOKEN` | unset | | If set (16–256 chars of `A-Z a-z 0-9 _ -`), `/metrics` requires `Authorization: Bearer <token>`; if unset, only loopback clients may read it |
| `SEARCH_IWARA_API_DOCS_ENABLED` | `false` | | Serve Swagger UI at `/api/docs` and the schema at `/api/openapi.json` (Swagger assets load from jsDelivr; the CSP is relaxed for that one path only) |
| `SEARCH_IWARA_WEB_THREADS` | `16` | | Worker threads for request handling; each keeps one read-only SQLite connection (8 MB page cache) |
| `SEARCH_IWARA_ALLOW_INDEXING` | `false` | | When false: `robots.txt` disallows everything, pages carry `noindex` |
| — | | `serve --proxy-headers/--no-proxy-headers` | Trust `X-Forwarded-*` (default on) … |
| — | | `serve --forwarded-allow-ips` | … only from these proxies (default `127.0.0.1`) |
| — | | `serve --reload` | Development auto-reload |

## Crawler

| Variable | Default | CLI | Description |
|---|---|---|---|
| `SEARCH_IWARA_REQUEST_CONCURRENCY` | `4` | `--request-concurrency` | Max in-flight requests and detail workers (1–64) |
| `SEARCH_IWARA_REQUEST_RATE` | `2.0` | `--request-rate` | Request-rate ceiling in req/s (adaptive: halves on 429/503) |
| `SEARCH_IWARA_LIST_PREFETCH_PAGES` | `4` | `sync full --list-prefetch-pages` | Listing pages fetched per batch |
| `SEARCH_IWARA_REQUEST_TIMEOUT_SECONDS` | `30` | | Per-request timeout |
| `SEARCH_IWARA_REQUEST_RETRIES` | `4` | | Retries for 408/425/429/5xx/timeouts/transport errors |
| `SEARCH_IWARA_BACKOFF_BASE_SECONDS` | `1.0` | | Full-jitter backoff base |
| `SEARCH_IWARA_BACKOFF_MAX_SECONDS` | `60` | | Backoff cap; `Retry-After` > 5× this gives up on the URL |
| `SEARCH_IWARA_RESPECT_ROBOTS` | `true` | | Honour robots.txt rules and `Crawl-delay` |
| `SEARCH_IWARA_USER_AGENT` | `search-iwara/<version> (+repo URL)` | | Identify the crawler honestly |
| `SEARCH_IWARA_PROXY` | unset | | Explicit proxy, e.g. `socks5://127.0.0.1:1080`, `http://proxy:3128` |
| `SEARCH_IWARA_TRUST_ENV` | `true` | | Use `HTTP(S)_PROXY`/`ALL_PROXY`/`NO_PROXY` from the environment |
| `SEARCH_IWARA_HTTP2` | `true` | | Negotiate HTTP/2 |
| `SEARCH_IWARA_DETAIL_MAX_ATTEMPTS` | `6` | | Stop retrying a failing detail page after this many attempts |
| `SEARCH_IWARA_DETAIL_REFRESH_WINDOW_DAYS` | `30` | | Movies published within this window get their details refreshed … |
| `SEARCH_IWARA_DETAIL_REFRESH_AFTER_HOURS` | `72` | | … once their details are older than this |
| `SEARCH_IWARA_DETAIL_REFRESH_LIMIT` | `500` | | Max refreshes per `sync latest` |
| `SEARCH_IWARA_RESUME_OVERLAP_PAGES` | `1` | | Pages re-scanned before the checkpoint when `sync full` resumes |
| `SEARCH_IWARA_SYNC_FAILURE_TOLERANCE` | `10` | | Failed details tolerated before `sync` exits with 1 (any failed listing page exits 1) |
| — | | `sync latest --stable-pages` | Stop after N consecutive pages without new movies (default 3) |
| — | | `--max-pages`, `sync full --start-page` | Bound or position a run |

## Logging

| Variable | Default | Description |
|---|---|---|
| `SEARCH_IWARA_LOG_FORMAT` | `auto` | `text`, `json`, or `auto` (text on a TTY, JSON otherwise) |
| `SEARCH_IWARA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Finished with failed listing pages or more failed details than the tolerance |
| 2 | Parser drift: the site's markup changed, run aborted (update the parser) |
| 75 | Another sync holds the lock; nothing done (systemd treats it as success) |
| 78 | Invalid configuration |
| 143 | Terminated by SIGTERM/SIGINT: committed work is kept, the run is recorded as `failed` |

`1` is also returned when robots.txt is unreachable (5xx/429/network): per RFC 9309 the crawler
then treats the whole site as disallowed and stops.

See [linux-deploy.md](linux-deploy.md) for the systemd/nginx/Docker variables
(`SEARCH_IWARA_SYNC_HOURS`, `SEARCH_IWARA_ALERT_WEBHOOK`, …) used by the deployment tooling.
