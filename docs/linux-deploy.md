# Linux Deployment

Search Iwara ships two production deployment paths:

- **systemd + nginx** on a Linux host (this document, `deploy/linux/`)
- **Docker / Compose** (`Dockerfile`, `compose.yaml`, see [Docker](#docker))

`deploy/linux/manage.py` is the single source of truth for the systemd path:
it creates the service account, writes the env file, renders every unit and
the nginx site, runs database migrations and restarts services. `install.sh`
is only a bootstrapper that installs prerequisites and then calls
`manage.py install --non-interactive`.

## What gets installed

| Item | Purpose |
|------|---------|
| `searchiwara` system user/group | Dedicated, non-login account that owns only the data and backup dirs |
| `/etc/search-iwara/search-iwara.env` | Runtime settings (mode `0600`, root-owned) |
| `search-iwara-web.service` | `search-iwara db migrate` (pre-start), then `search-iwara serve` |
| `search-iwara-sync.service` + `.timer` | `search-iwara sync latest` every N hours (`OnCalendar=`, randomized, persistent) |
| `search-iwara-backup.service` + `.timer` | Daily SQLite online backup with rotation |
| `search-iwara-alert@.service` | Runs when any of the above fails (`OnFailure=`): journal entry + optional webhook |
| nginx site `search-iwara.conf` | Reverse proxy, TLS, gzip, static files, rate limits |

The services run `${APP_DIR}/.venv/bin/search-iwara` directly. The venv is
built once with `uv sync --frozen --no-dev` during install/update, so a
service restart never resolves dependencies or touches the network.

## Prerequisites

- A Linux host with `systemd` (Debian/Ubuntu, RHEL/Fedora, Arch, openSUSE, Alpine+systemd).
- The repository checked out on the server. **Recommended location:
  `/opt/search-iwara`, owned by root.** The service account then gets read-only
  access to the code. A checkout under `/home` works too (units switch to
  `ProtectHome=read-only`), but the parent directories must be traversable
  (`o+x`) by the service account; the installer warns if they are not.

Everything else is installed automatically:

- `uv` (pinned release, default `0.12.19`, override with `--uv-version` or
  `UV_VERSION=`). The versioned installer is downloaded to a file (never piped
  into a shell); set `UV_INSTALLER_SHA256=` to verify its checksum as well.
- Python ≥ 3.13 via uv when the system Python is older. uv-managed Python lives
  in `/usr/local/share/search-iwara/python` so the unprivileged service can run it.
- nginx, when nginx mode is used, via the system package manager.

## Install

```bash
sudo git clone https://github.com/<you>/iwara-search /opt/search-iwara
cd /opt/search-iwara

# nginx on port 80, sync every 6 hours
sudo ./deploy/linux/install.sh --server-name search.example.com --sync-hours 6

# HTTPS with an existing certificate
sudo ./deploy/linux/install.sh \
  --server-name search.example.com \
  --tls-cert /etc/letsencrypt/live/search.example.com/fullchain.pem \
  --tls-key  /etc/letsencrypt/live/search.example.com/privkey.pem

# No nginx: bind the app directly to a public port.
# A random /metrics bearer token is generated and stored in the env file.
sudo ./deploy/linux/install.sh --skip-nginx --web-host 0.0.0.0 --web-port 8000
```

Or use the interactive manager, which asks for every value:

```bash
sudo ./deploy/linux/manage.py
```

Re-running `install.sh` is safe. Options you do not pass keep their current
value from the env file (for example `sudo ./deploy/linux/install.sh --sync-hours 2`
only changes the sync interval). Run `./deploy/linux/install.sh --help` for all
options.

To preview what would be written without touching the system:

```bash
./deploy/linux/manage.py render --env-file /etc/search-iwara/search-iwara.env --output /tmp/search-iwara-preview
```

## Interactive manager

`sudo ./deploy/linux/manage.py` offers:

1. Show status (services, timers, last sync/backup result, `/healthz`)
2. Reconfigure deployment (mode, domain, TLS, ports, paths)
3. Update sync / ops settings (interval, crawler politeness, proxy, backups, alerts)
4. Run `sync latest` now
5. Run `sync full` now
6. Back up the database now
7. **Update**: `git pull --ff-only` → `uv sync --frozen --no-dev` → `db migrate` → re-render units → restart
8. Restart the web service

Non-interactive equivalents: `manage.py update`, `manage.py backup`,
`manage.py status`, `manage.py install --non-interactive ...`.

Manual syncs run as the service account (`subprocess` with `user=`, `group=`
and `extra_groups=[]`, so root's supplementary groups are dropped).

`manage.py` is a thin entry point for the standard-library package
[`deploy/linux/search_iwara_deploy/`](../deploy/linux/search_iwara_deploy):
`shell` (the only module that spawns processes), `config` (env file, legacy
migration, validation), `render` (systemd units, nginx), `system` (applying a
configuration to the host), `prompts` and `cli`. It is linted with ruff and
type-checked with `mypy --strict` in CI like the application.

## Runtime settings

All settings live in `/etc/search-iwara/search-iwara.env`
(see [`search-iwara.env.example`](../deploy/linux/search-iwara.env.example)).
Change them through `manage.py` (option 3) so units are re-rendered, or edit
the file and restart the affected services.

| Variable | Default | Meaning |
|----------|---------|---------|
| `SEARCH_IWARA_DB` | `APP_DIR/data/oreno3d.sqlite3` | SQLite database path |
| `SEARCH_IWARA_HOST` / `SEARCH_IWARA_PORT` | `127.0.0.1` / `8000` | Web bind address |
| `SEARCH_IWARA_REQUEST_CONCURRENCY` | `4` | Max concurrent requests to the source site |
| `SEARCH_IWARA_REQUEST_RATE` | `2.0` | Global request rate limit (requests/second) |
| `SEARCH_IWARA_LIST_PREFETCH_PAGES` | `4` | Listing pages fetched ahead during `sync full` |
| `SEARCH_IWARA_PROXY` | unset | Outbound proxy, e.g. `socks5://127.0.0.1:1080` |
| `SEARCH_IWARA_TRUST_ENV` | `true` | Honour `HTTP(S)_PROXY`/`ALL_PROXY` from the environment |
| `SEARCH_IWARA_LOG_FORMAT` / `SEARCH_IWARA_LOG_LEVEL` | `json` / `INFO` | Structured logs for journald |
| `SEARCH_IWARA_BACKUP_DIR` / `SEARCH_IWARA_BACKUP_KEEP` | `<db dir>/backups` / `7` | Backup target and retention |
| `SEARCH_IWARA_STABLE_PAGES` / `SEARCH_IWARA_MAX_PAGES` | `3` / unset | `sync latest` stop condition / page cap |
| `SEARCH_IWARA_ALERT_WEBHOOK` | unset | URL that receives a JSON POST when a unit fails |
| `SEARCH_IWARA_METRICS_TOKEN` | unset (generated in `public` mode) | Bearer token required by `/metrics`; without it `/metrics` is only served on loopback binds |
| `SEARCH_IWARA_API_DOCS_ENABLED` | `false` | Serve the OpenAPI docs at `/api/docs` |
| `SEARCH_IWARA_SYNC_HOURS` | `6` | Timer interval (1–24; values that do not divide 24 restart at midnight) |
| `SEARCH_IWARA_HSTS_MAX_AGE` | `63072000` | HSTS max-age in HTTPS mode (`0` disables) |

Env files written by older releases are migrated automatically:
`REQUEST_DELAY_MS` becomes an equivalent `REQUEST_RATE` (never faster than
2 req/s), `DETAIL_BATCH_SIZE` is dropped, and the old aggressive defaults
(concurrency 12, prefetch 8) are lowered to the new polite defaults.

## Security hardening

- **Dedicated account.** Services run as `searchiwara` (system user, no login
  shell, home = data dir). It owns only the data and backup directories; the
  code checkout stays root-owned and read-only.
- **systemd sandbox** on every unit: `ProtectSystem=strict` with
  `ReadWritePaths=` limited to the data/backup dirs, `ProtectHome=`,
  `PrivateTmp`, `PrivateDevices`, `NoNewPrivileges`, empty
  `CapabilityBoundingSet=`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`,
  `SystemCallFilter=@system-service`, `MemoryDenyWriteExecute`,
  `ProtectKernel*`, `ProtectControlGroups`, `ProtectClock`, `ProtectHostname`,
  `ProtectProc=invisible`, `RestrictNamespaces`, `RestrictRealtime`,
  `LockPersonality`, `UMask=0027`. Check the result with
  `systemd-analyze security search-iwara-web.service`.
- **nginx**: `server_tokens off`, 16 KiB request body cap, per-IP rate limits
  (pages 10 r/s burst 20, `/api/` 20 r/s burst 40, answered with 429),
  `/metrics` restricted to loopback, TLS 1.2/1.3 only, HSTS, `http2 on;` on
  nginx ≥ 1.25.1 (older nginx gets the legacy `listen ... http2` form
  automatically).
- **App**: uvicorn runs with `--proxy-headers` trusting only `127.0.0.1`
  (`SEARCH_IWARA_FORWARDED_ALLOW_IPS` to change) and without a `Server` header;
  the app itself sets CSP and other security headers.
- **Env file** is `0600 root` because the alert webhook may contain a token.

## nginx

The site file is written to `/etc/nginx/sites-available/search-iwara.conf`
(+ `sites-enabled` symlink) on Debian-style systems, or
`/etc/nginx/conf.d/search-iwara.conf` elsewhere. It is included inside nginx's
`http {}` block, which is why the `limit_req_zone` declarations sit at the top
of the file. If `nginx -t` rejects a new config, the previous file is restored.

Static assets (`/static/`) are served straight from
`APP_DIR/search_iwara/static/` with a one-year `immutable` cache (URLs carry a
content hash `?v=`), and responses are gzip-compressed.

### TLS

Pass `--tls-cert` / `--tls-key` (or choose HTTPS in `manage.py`). With certbot:

```bash
sudo mkdir -p /var/www/html
sudo certbot certonly --webroot -w /var/www/html -d search.example.com
sudo ./deploy/linux/install.sh \
  --tls-cert /etc/letsencrypt/live/search.example.com/fullchain.pem \
  --tls-key  /etc/letsencrypt/live/search.example.com/privkey.pem
```

Both the HTTP and HTTPS sites serve `/.well-known/acme-challenge/` from
`/var/www/html`, so renewals keep working. Prefer `certonly` over
`certbot --nginx`, so certbot does not rewrite a file that `manage.py` owns.

## Health checks and metrics

| Endpoint | Meaning |
|----------|---------|
| `GET /healthz` | Process is alive (used by `manage.py status`, Docker `HEALTHCHECK`) |
| `GET /readyz` | Database is readable; `503` otherwise |
| `GET /metrics` | Prometheus metrics: request latency, dataset size, last successful sync, last run's requests/retries/throttling |

Who can read `/metrics`:

| Deployment | Access |
|------------|--------|
| `nginx` mode | App binds `127.0.0.1`; nginx answers `/metrics` only to `127.0.0.1`/`::1` (`deny all` otherwise). Scrape from the host. |
| `local` mode | Loopback bind only. |
| `public` mode (`--skip-nginx --web-host 0.0.0.0`) | The installer generates `SEARCH_IWARA_METRICS_TOKEN`; requests need `Authorization: Bearer <token>`. Without a token the app does not serve `/metrics` on a public bind at all. |
| Docker | The container binds `0.0.0.0`, so set `SEARCH_IWARA_METRICS_TOKEN` to enable `/metrics`. |

Scrape job on the same host (nginx/local mode):

```yaml
- job_name: search-iwara
  static_configs: [{ targets: ["127.0.0.1:8000"] }]
```

Scrape job for a token-protected (public or Docker) instance — copy the token
from the env file (`sudo grep METRICS_TOKEN /etc/search-iwara/search-iwara.env`)
into a file readable by Prometheus:

```yaml
- job_name: search-iwara
  scheme: http
  authorization:
    type: Bearer
    credentials_file: /etc/prometheus/search-iwara.token
  static_configs: [{ targets: ["search.example.com:8000"] }]
```

### Alerting rules

[`deploy/prometheus/alerts.yml`](../deploy/prometheus/alerts.yml) ships five
rules (job name `search-iwara`):

| Alert | Fires when |
|-------|-----------|
| `SearchIwaraDown` | the scrape target is down for 5 min |
| `SearchIwaraSyncStale` | no successful sync for 2 × the configured interval (`search_iwara_sync_interval_seconds`, exported from `SEARCH_IWARA_SYNC_HOURS`; 6 h assumed if unset) |
| `SearchIwaraSyncFailed` | the most recent sync run failed (e.g. parser drift) |
| `SearchIwaraThrottled` | the last run got more than 10 HTTP 429/503 responses |
| `SearchIwaraHighLatency` | p95 request latency above 500 ms for 15 min |

```bash
sudo install -m 0644 deploy/prometheus/alerts.yml /etc/prometheus/rules/search-iwara-alerts.yml
promtool check rules /etc/prometheus/rules/search-iwara-alerts.yml
# prometheus.yml:
#   rule_files: ["/etc/prometheus/rules/search-iwara-alerts.yml"]
sudo systemctl reload prometheus
```

## Logs, failures and alerts

```bash
systemctl status search-iwara-web.service
systemctl list-timers 'search-iwara-*'
journalctl -u search-iwara-web.service -f
journalctl -u search-iwara-sync.service -e
journalctl -p err -u 'search-iwara-alert@*'
```

Logs are JSON by default (`SEARCH_IWARA_LOG_FORMAT=json`) and progress bars
are disabled when there is no TTY, so journald receives clean records.

When the web, sync or backup unit fails, `search-iwara-alert@<unit>.service`
writes an `err`-priority journal entry. If `SEARCH_IWARA_ALERT_WEBHOOK` is set
it also POSTs:

```json
{"text": "search-iwara ALERT: search-iwara-sync.service failed on host (result=exit-code, exit=2) ...",
 "unit": "search-iwara-sync.service", "host": "host", "result": "exit-code",
 "exit_status": "2", "timestamp": 1790000000}
```

This works with ntfy, Gotify-style endpoints and Slack/Discord-compatible
incoming webhooks (which read the `text` field).

### Sync exit codes

| Code | Meaning | Unit result |
|------|---------|-------------|
| `0` | Success | success |
| `1` | Too many items failed (see log) | **failed → alert** |
| `2` | Parser drift: a listing page returned no items, the site layout probably changed | **failed → alert** |
| `75` | Another sync holds the lock (`EX_TEMPFAIL`) | success (`SuccessExitStatus=75`) |

## Backup and restore

`search-iwara-backup.timer` runs `search-iwara db backup` daily (04:00 plus up
to 30 min random delay, catch-up after downtime). It uses SQLite's online
backup API, so it is consistent while the web service and syncs keep running,
and keeps the newest `SEARCH_IWARA_BACKUP_KEEP` files.

```bash
sudo ./deploy/linux/manage.py backup          # back up now
ls -l /opt/search-iwara/data/backups
```

Restore:

```bash
sudo systemctl stop search-iwara-web.service search-iwara-sync.timer
sudo install -o searchiwara -g searchiwara -m 0640 \
  /opt/search-iwara/data/backups/<file>.sqlite3 /opt/search-iwara/data/oreno3d.sqlite3
sudo rm -f /opt/search-iwara/data/oreno3d.sqlite3-wal /opt/search-iwara/data/oreno3d.sqlite3-shm
sudo systemctl start search-iwara-web.service search-iwara-sync.timer
```

Copy backups off the host as well (e.g. `rsync`/`restic` the backup dir).

## Upgrading

```bash
sudo ./deploy/linux/manage.py update
```

This runs `git pull --ff-only` (as the checkout owner), `uv sync --frozen
--no-dev`, `db migrate`, re-renders units and nginx config, and restarts the
web service. Migrations are also re-run by `ExecStartPre=` on every web start.

## Docker

```bash
docker compose up -d                 # web + sync loop (6 h) + daily backups
docker compose logs -f sync
docker compose exec backup search-iwara db backup   # one-off backup now
```

Services:

| Service | What it does |
|---------|--------------|
| `web` | `db migrate`, then `serve` on `127.0.0.1:${SEARCH_IWARA_PORT:-8000}`; `HEALTHCHECK` on `/healthz` |
| `sync` | [`sync-loop.sh`](../deploy/docker/sync-loop.sh): `sync latest` every `SYNC_INTERVAL_SECONDS` (default 21600) plus 0–10 min random jitter. Exit `0`/`75` → next cycle; `1` → logged, retried next cycle; `2` (parser drift) → writes `/data/.sync-parser-drift`, exits non-zero and stays idle (health check unhealthy) until the image is upgraded |
| `backup` | [`backup-loop.sh`](../deploy/docker/backup-loop.sh): `db backup` once a day plus 0–30 min jitter, keeping `BACKUP_KEEP` (default 7) files in `/data/backups` |

The image is multi-stage (uv builder → `python:3.13-slim`), runs as UID 10001,
stores everything in the `/data` volume and has a `HEALTHCHECK` on `/healthz`.
Base images are **pinned by digest** (`python:3.13-slim@sha256:…`,
`ghcr.io/astral-sh/uv:<version>@sha256:…`); Dependabot's `docker` ecosystem
bumps tag and digest together. Compose adds a read-only root filesystem,
`cap_drop: [ALL]` and `no-new-privileges`. Set `SEARCH_IWARA_PROXY`,
`SEARCH_IWARA_REQUEST_RATE`, `SYNC_INTERVAL_SECONDS`, `BACKUP_KEEP` or
`SEARCH_IWARA_METRICS_TOKEN` in a `.env` file next to `compose.yaml`. Put nginx
or another TLS proxy in front for public access.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Sync logs `lock held`, exit 75 | A previous or manual sync is still running. Nothing to do; the timer run is skipped and not counted as a failure. |
| Sync fails with exit 2 (parser drift) | The source site changed its HTML; update the app (`manage.py update`) or report an issue. Existing data is untouched. In Docker the `sync` service stays idle until the image is upgraded (or `/data/.sync-parser-drift` is removed). |
| `/metrics` returns 404 | Public bind without `SEARCH_IWARA_METRICS_TOKEN` (served only on loopback or with a token). Re-run `install.sh --skip-nginx --web-host 0.0.0.0` to generate one, or scrape through nginx from the host. |
| `/api/docs` returns 404 | The OpenAPI docs are off by default; enable with `install.sh --api-docs` (or `SEARCH_IWARA_API_DOCS_ENABLED=true`). |
| `Using SOCKS proxy, but the 'socksio' package is not installed` | Old install. Run `manage.py update` (SOCKS support is now a regular dependency). Set `SEARCH_IWARA_PROXY=socks5://...` or `SEARCH_IWARA_TRUST_ENV=false` to ignore `ALL_PROXY`. |
| Many `429` responses in the sync log | Lower `SEARCH_IWARA_REQUEST_RATE` / `SEARCH_IWARA_REQUEST_CONCURRENCY`. The crawler already backs off and honours `Retry-After`. |
| `.venv/bin/search-iwara is missing` | Run `sudo ./deploy/linux/manage.py update` (or `uv sync --frozen --no-dev` in the app dir). |
| `status=226/NAMESPACE` or `Permission denied` on start | A path in `ReadWritePaths=` is missing, or the checkout is under `/home` with non-traversable parents. Move it to `/opt/search-iwara` and re-run `install.sh`. |
| `database is locked` | Only one writer at a time; long `sync full` runs block other syncs through the lock. Wait, or stop the timer while running a full sync. |
| nginx returns 403 for `/static/` | nginx's user cannot read `APP_DIR/search_iwara/static`; make the checkout world-readable (`chmod -R o+rX`). |
| `nginx: [emerg] unknown directive "http2"` | nginx < 1.25.1; re-run `install.sh`, which detects the version and renders `listen 443 ssl http2` instead. |
