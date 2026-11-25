# Troubleshooting

### `sync` exits with code `2` ("parser drift")

Oreno3D changed its HTML layout: a listing page had no movie grid, parsed to zero items, or 5 detail pages in one run lacked a title. Sync aborts immediately so corrupted records are never written, and existing data stays intact.

- On a deployed server or Docker stack, upgrade to the latest release (`sudo ./deploy/linux/manage.py update` or `docker compose pull && docker compose up -d`). In Docker, remove `/data/.sync-parser-drift` if needed after upgrading.
- When developing a parser fix, compare `tests/fixtures/*.html` against the live markup, update `search_iwara/parsers.py`, and run `uv run pytest tests/test_parsers.py`.

### `sync` exits with code `75` ("lock held")

Another sync process (scheduled timer or manual run) already holds `<db>.sync.lock`. No action is required; `flock` releases the lock automatically when that process exits.

### `sync` exits with code `1`

Either a listing page failed, failed detail fetches exceeded `SEARCH_IWARA_SYNC_FAILURE_TOLERANCE`, or `robots.txt` returned `5xx`/`429`/network failure (per RFC 9309, unreachable `robots.txt` halts crawling for that run).

Inspect recent per-item errors in SQLite:

```bash
sqlite3 data/oreno3d.sqlite3 \
  "SELECT entity_type, entity_id, error_type, attempts, next_retry_at FROM crawl_errors ORDER BY last_failed_at DESC LIMIT 20"
```

Failed details retry automatically on subsequent runs with exponential backoff. If logs show repeated `HTTP 429` or `503` responses, lower `SEARCH_IWARA_REQUEST_RATE` and `SEARCH_IWARA_REQUEST_CONCURRENCY`.

### `sync` exits with code `143`

The process received `SIGTERM` or `SIGINT` (`systemctl stop`, `docker stop`, or unit timeout). All previously committed batches remain in SQLite, and the next run resumes from the last contiguous checkpoint.

### Crawler logs "Redirect target ... disallowed" or "Response body exceeded ..."

`Oreno3dClient` blocks redirects that leave the configured `https` origin, violate `robots.txt` on any hop, or exceed 5 hops, and aborts streaming responses larger than `2 MiB` (`robots.txt`) or `10 MiB` (HTML). Persistent errors usually point to an intercepting captive portal or misconfigured proxy.

### SOCKS proxy errors during `sync`

If your shell sets `ALL_PROXY=socks5://...`, `httpx[socks,http2]` is included in standard dependencies; run `uv sync` if using an older virtual environment. Set `SEARCH_IWARA_TRUST_ENV=false` to ignore ambient proxy variables, or set `SEARCH_IWARA_PROXY=socks5://127.0.0.1:1080` explicitly.

### Hiding or restoring specific videos (takedowns)

To remove one or more works from search results, detail pages, autocomplete, rankings, and sitemaps without future syncs re-importing them:

```bash
uv run search-iwara db suppress 123456 --reason "rightsholder request"
# Restore if needed:
uv run search-iwara db unsuppress 123456
```

### Verifying or rebuilding full-text search indexes

To verify that `movie_search` and `movie_search_short` match all `active` movies (with no pending deferred `fts_dirty` work), or to stream-rebuild them in 5,000-row batches:

```bash
uv run search-iwara db reindex --verify
uv run search-iwara db reindex
```

### `/metrics` or `/api/docs` returns `404` / `401`

- `/metrics` only answers loopback (`127.0.0.1` / `::1`) requests unless `SEARCH_IWARA_METRICS_TOKEN` is configured. With a token set, pass `Authorization: Bearer <token>` (`401` otherwise).
- `/api/docs` is disabled by default; set `SEARCH_IWARA_API_DOCS_ENABLED=true` (or `--api-docs` in `install.sh`) to enable it.

### `database is locked`

WAL mode allows concurrent readers alongside one writer, with a `10 s` `busy_timeout`. Persistent lock errors almost always indicate that the SQLite file is stored on NFS, SMB, or another network filesystem without reliable POSIX locking. Store the database on local disk.

### Thumbnails show placeholders instead of images

Thumbnails load directly from `oreno3d.com` with `referrerpolicy="no-referrer"`. When upstream hot-link rules or local network policies block them, cards fall back to an inline placeholder frame. If you proxy thumbnails through your own domain, update `img-src` in `search_iwara/web/security.py`.

### Result count displays `10,000+`

`COUNT(*)` stops at `SEARCH_IWARA_MAX_RESULT_WINDOW` (default `10,000`) so broad queries stay fast. Add more filters or increase `SEARCH_IWARA_MAX_RESULT_WINDOW`.

### Short 1–2 letter Latin queries do not match inside words

Queries of 3+ characters use trigram substring matching, and 1–2 character CJK queries match anywhere via unigram/bigram tokens. One- and two-letter Latin tokens (`mm`, `3d`) intentionally match **word prefixes** (`mm` matches `MMD`, not `summer`) to avoid noisy partial hits. Enter at least 3 letters for mid-word Latin substrings.

### `/readyz` returns `503` with schema mismatch

The database file was opened against an unmigrated or newer schema version. Run `search-iwara db migrate` using the current application release (downgrading a newer schema is refused safely).

### `systemd` service fails with `226/NAMESPACE` or `nginx` `403` on `/static/`

- `226/NAMESPACE` or `Permission denied`: a parent directory above the checkout (commonly `/home/<user>`) lacks world-traverse (`o+x`) permission. Move the checkout to `/opt/search-iwara` and re-run `sudo ./deploy/linux/install.sh`.
- `403` on `/static/`: ensure `nginx` can read `APP_DIR/search_iwara/static` (`chmod -R o+rX /opt/search-iwara`).
