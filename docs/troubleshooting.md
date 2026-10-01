# Troubleshooting

### `sync` fails with "HTTP client dependency missing … socksio"

Your environment defines a SOCKS proxy (`ALL_PROXY=socks5://…`). Current releases ship
`httpx[socks,http2]`, so run `uv sync` to install it. To bypass the environment proxy set
`SEARCH_IWARA_TRUST_ENV=false`, or pin one explicitly with `SEARCH_IWARA_PROXY=socks5://host:port`.

### `sync` exits with code 2 ("parser drift")

oreno3d.com changed its markup: a listing page had no movie grid, parsed to zero movies, or
several detail pages had no title. Nothing is deleted; the run stops early so bad data is not
written. Check `tests/fixtures/*.html` against the live site, update `parsers.py`, and run
`uv run pytest tests/test_parsers.py`.

### `sync` exits with code 75

Another sync (timer or manual) holds `<db>.sync.lock`. Wait for it to finish. The lock is an
advisory `flock`, released automatically if the process dies.

### `sync` exits with code 1

Some listing pages failed, or more details failed than `SEARCH_IWARA_SYNC_FAILURE_TOLERANCE`.
Failures are recorded and retried automatically on later runs with growing intervals:

```bash
sqlite3 data/oreno3d.sqlite3 \
  "SELECT entity_type, entity_id, error_type, attempts, next_retry_at FROM crawl_errors ORDER BY last_failed_at DESC LIMIT 20"
```

Frequent `HTTP 429`/`503` means the site is throttling you: lower `SEARCH_IWARA_REQUEST_RATE`
and `SEARCH_IWARA_REQUEST_CONCURRENCY`.

### `sync` exits with code 1 and "robots.txt … unreachable (RFC 9309)"

The site answered robots.txt with a 5xx/429 or could not be reached. RFC 9309 requires a crawler
to treat that as "everything disallowed", so the run stopped without crawling. It is retried on
the next scheduled run; check your proxy settings if it persists.

### `sync` exits with code 143

The process received SIGTERM/SIGINT (`systemctl stop`, `docker stop`, the unit's
`TimeoutStartSec`). Work committed so far is kept and the run is recorded as `failed`; the next
run continues where it left off.

### `/metrics` returns 404 or 401

Without `SEARCH_IWARA_METRICS_TOKEN` only loopback clients can read metrics (404 for everyone
else). With a token, send `Authorization: Bearer <token>` (401 otherwise). `/api/docs` returns 404
unless `SEARCH_IWARA_API_DOCS_ENABLED=true`.

### `database is locked`

Readers never block the writer in WAL mode, and connections wait up to 10 s (`busy_timeout`).
Persistent lock errors usually mean the database sits on a network filesystem (NFS/SMB) that
does not support SQLite's locking — keep it on local disk.

### Thumbnails do not load

Thumbnails are hot-linked from oreno3d.com with `referrerpolicy="no-referrer"`. If they are
blocked (network policy, the site's hot-link protection), cards show a placeholder instead.
The page's Content-Security-Policy only allows images from `oreno3d.com`; adjust
`web/security.py` if you proxy thumbnails elsewhere.

### The UI shows "10,000+ results"

Counting is capped at `SEARCH_IWARA_MAX_RESULT_WINDOW` to keep every query bounded. Narrow the
search, or raise the window (deep pages get slower).

### A one- or two-letter Latin word matches less than expected

Tokens of three or more characters match anywhere (trigram substring search). One- and
two-character CJK tokens match any occurrence too. One- and two-letter Latin tokens match the
*start of a word* ("mm" finds "MMD" but not "summer") — substring matches that short are almost
always noise. Type three letters for a substring match. On SQLite older than 3.34 (no trigram
tokenizer) 3+ character tokens use a slower `LIKE` scan — upgrade SQLite/Python.

### `readyz` returns 503 with a schema mismatch

The database was migrated by a newer or older build. Run `search-iwara db migrate` with the
current build (it refuses to downgrade a newer schema).
