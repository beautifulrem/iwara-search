# Linux & Docker Deployment

Search Iwara supports two production deployment setups:

- **Docker Compose** using the prebuilt multi-arch (`linux/amd64`, `linux/arm64`) image on GHCR (see [Docker](#docker))
- **`systemd` + `nginx`** directly on a Linux host (`deploy/linux/`, documented below)

For the host-installed path, `deploy/linux/manage.py` manages the service user, `/etc/search-iwara/search-iwara.env`, `systemd` units, `nginx` virtual host, database migrations, and service restarts. `deploy/linux/install.sh` bootstraps prerequisites (`uv`, Python, `nginx`) and delegates to `manage.py install --non-interactive`.

## Docker

### Standalone Compose (Recommended)

`compose.yaml` pulls `ghcr.io/beautifulrem/iwara-search:latest` (`linux/amd64` and `linux/arm64`) and requires no source checkout:

```bash
mkdir search-iwara && cd search-iwara
curl -fsSLO https://raw.githubusercontent.com/beautifulrem/iwara-search/main/compose.yaml
docker compose up -d
```

Common operations:

```bash
docker compose logs -f sync                                    # watch sync logs
docker compose exec sync search-iwara sync full                # resumable full mirror
docker compose exec backup search-iwara db backup --compress   # immediate compressed backup
docker compose pull && docker compose up -d                    # upgrade to latest release
```

To pin a specific release or run a locally built image, set `SEARCH_IWARA_IMAGE` in `.env` next to `compose.yaml`:

```ini
SEARCH_IWARA_IMAGE=ghcr.io/beautifulrem/iwara-search:0.3.0
SEARCH_IWARA_PORT=8000
SEARCH_IWARA_PROXY=
SYNC_INTERVAL_SECONDS=21600
BACKUP_KEEP=7
```

To build from a local git checkout instead of pulling from GHCR:

```bash
docker build -t search-iwara:local .
SEARCH_IWARA_IMAGE=search-iwara:local docker compose up -d
```

### Compose Services & Container Design

| Service | Behaviour |
|---|---|
| `web` | Runs `search-iwara db migrate`, then `search-iwara serve` bound to `127.0.0.1:${SEARCH_IWARA_PORT:-8000}` on the host; `HEALTHCHECK` probes `/healthz` |
| `sync` | Runs [`sync-loop.sh`](../deploy/docker/sync-loop.sh): executes an immediate `sync latest` on startup, then repeats every `SYNC_INTERVAL_SECONDS` (default `21600`, plus `0`–`10 min` jitter) while forwarding `SIGTERM` cleanly. Exit `2` (parser drift) writes `/data/.sync-parser-drift` and idles unhealthy until the image is upgraded |
| `backup` | Runs [`backup-loop.sh`](../deploy/docker/backup-loop.sh): executes `db backup` every 24 hours (plus `0`–`30 min` jitter), keeping `BACKUP_KEEP` (default `7`) snapshots in `/data/backups` |

The `Dockerfile` uses a multi-stage build (`uv` builder -> `python:3.15-slim`), runs as unprivileged UID/GID `10001`, stores state in `/data`, and pins every base image by SHA-256 digest. `compose.yaml` adds `init: true`, `read_only: true`, `cap_drop: [ALL]`, and `no-new-privileges:true`. Place `nginx`, Caddy, or another reverse proxy in front when exposing the UI beyond localhost.

---

## Linux Host (`systemd` + `nginx`)

### Installed Components

| Component | Purpose |
|---|---|
| `searchiwara` user & group | Non-login system account owning only the data and backup directories |
| `/etc/search-iwara/search-iwara.env` | Environment configuration (`0600`, owned by `root`) |
| `search-iwara-web.service` | Runs `db migrate` (`ExecStartPre=`), then `search-iwara serve` with `WatchdogSec=90s` + `OOMPolicy=kill` |
| `search-iwara-sync.service` + `.timer` | Runs `sync latest` every `N` hours (`OnCalendar=`, randomized delay, `Persistent=true`) |
| `search-iwara-backup.service` + `.timer` | Daily online SQLite backup (`--compress`) with file rotation |
| `search-iwara-alert@.service` | `OnFailure=` unit logging `err` journal entries and posting validated webhook alerts |
| `nginx` site `search-iwara.conf` | Reverse proxy, TLS 1.2/1.3, gzip, immutable static caching, per-IP rate limits |

Services execute `${APP_DIR}/.venv/bin/search-iwara` directly. The virtual environment is built once with `uv sync --frozen --no-dev` during install or update so service restarts never touch the network.

### Prerequisites

- A Linux distribution with `systemd` (Debian/Ubuntu, RHEL/Rocky/Fedora, Arch, openSUSE, Alpine with `systemd`).
- Repository cloned on the host, ideally at `/opt/search-iwara` owned by `root` so the service account only has read access to code. Checkouts under `/home` also work (units switch to `ProtectHome=read-only`), provided parent directories grant traverse (`o+x`) permissions.
- `install.sh` automatically installs `uv` (downloaded to disk rather than piped into `sh`), Python `>= 3.13` under `/usr/local/share/search-iwara/python` if needed, and `nginx` when reverse-proxy mode is enabled.

### Install Commands

```bash
sudo git clone https://github.com/beautifulrem/iwara-search.git /opt/search-iwara
cd /opt/search-iwara

# HTTP behind nginx on port 80, syncing every 6 hours
sudo ./deploy/linux/install.sh --server-name search.example.com --sync-hours 6

# HTTPS with an existing certificate
sudo ./deploy/linux/install.sh \
  --server-name search.example.com \
  --tls-cert /etc/letsencrypt/live/search.example.com/fullchain.pem \
  --tls-key  /etc/letsencrypt/live/search.example.com/privkey.pem

# Direct bind without nginx (generates a random /metrics bearer token automatically)
sudo ./deploy/linux/install.sh --skip-nginx --web-host 0.0.0.0 --web-port 8000
```

Re-running `install.sh` is idempotent: omitted flags keep their existing values from `/etc/search-iwara/search-iwara.env`. To inspect generated units without modifying the host:

```bash
./deploy/linux/manage.py render --env-file /etc/search-iwara/search-iwara.env --output /tmp/search-iwara-preview
```

> [!TIP]
> **Low-RAM VPS (`<= 1 GiB` RAM):** `search-iwara-web.service` enables `WatchdogSec=90s` + `OOMPolicy=kill`, and SQLite automatically scales `mmap_size` down to `32 MiB` on `< 1.5 GiB` cgroups/hosts. If you add a custom systemd memory drop-in, set `MemoryMax=` without `MemoryHigh=` so cgroup v2 triggers a clean restart rather than synchronous reclaim throttling.

### Interactive Manager (`manage.py`)

Run `sudo ./deploy/linux/manage.py` for an interactive menu covering service status, domain/TLS reconfiguration, crawler/proxy settings, immediate `sync latest` / `sync full` / `backup` runs, and in-place upgrades.

Non-interactive subcommands:

```bash
sudo ./deploy/linux/manage.py status
sudo ./deploy/linux/manage.py update    # git pull --ff-only -> uv sync -> db migrate -> re-render -> restart
sudo ./deploy/linux/manage.py backup
```

### Deployment Environment Variables

Configured in `/etc/search-iwara/search-iwara.env` (see [`search-iwara.env.example`](../deploy/linux/search-iwara.env.example)):

| Variable | Default | Purpose |
|---|---|---|
| `SEARCH_IWARA_DB` | `APP_DIR/data/oreno3d.sqlite3` | SQLite database file |
| `SEARCH_IWARA_HOST` / `SEARCH_IWARA_PORT` | `127.0.0.1` / `8000` | Application listen address |
| `SEARCH_IWARA_REQUEST_CONCURRENCY` | `4` | Concurrent upstream HTTP requests |
| `SEARCH_IWARA_REQUEST_RATE` | `2.0` | Upstream request ceiling (req/s) |
| `SEARCH_IWARA_LIST_PREFETCH_PAGES` | `4` | Prefetch batch size for `sync full` |
| `SEARCH_IWARA_PROXY` | unset | Outbound proxy (`socks5://127.0.0.1:1080`, `http://...`) |
| `SEARCH_IWARA_TRUST_ENV` | `true` | Honour `HTTP(S)_PROXY` / `ALL_PROXY` environment variables |
| `SEARCH_IWARA_LOG_FORMAT` / `SEARCH_IWARA_LOG_LEVEL` | `json` / `INFO` | Structured journald logging |
| `SEARCH_IWARA_BACKUP_DIR` / `SEARCH_IWARA_BACKUP_KEEP` | `<db_dir>/backups` / `7` | Backup directory and retained snapshot count |
| `SEARCH_IWARA_BACKUP_COMPRESS` | `true` (`systemd`) | Write `.sqlite3.gz` compressed snapshots |
| `SEARCH_IWARA_STABLE_PAGES` / `SEARCH_IWARA_MAX_PAGES` | `3` / unset | `sync latest` stop threshold and optional page cap |
| `SEARCH_IWARA_SYNC_HOURS` | `6` | `systemd` sync timer interval (`1`–`24` hours) |
| `SEARCH_IWARA_ALERT_WEBHOOK` | unset | HTTPS/HTTP webhook URL receiving JSON POST payloads on unit failure |
| `SEARCH_IWARA_METRICS_TOKEN` | unset (generated in `public` mode) | Bearer token required on `/metrics` when exposed publicly |
| `SEARCH_IWARA_API_DOCS_ENABLED` | `false` | Enable `/api/docs` |
| `SEARCH_IWARA_HSTS_MAX_AGE` | `63072000` | `Strict-Transport-Security` max-age in HTTPS mode (`0` disables) |

### TLS with Certbot

Use `certbot certonly --webroot` rather than `certbot --nginx` so Certbot does not overwrite the `nginx` config managed by `manage.py`:

```bash
sudo mkdir -p /var/www/html
sudo certbot certonly --webroot -w /var/www/html -d search.example.com
sudo ./deploy/linux/install.sh \
  --server-name search.example.com \
  --tls-cert /etc/letsencrypt/live/search.example.com/fullchain.pem \
  --tls-key  /etc/letsencrypt/live/search.example.com/privkey.pem
```

Both HTTP and HTTPS templates serve `/.well-known/acme-challenge/` from `/var/www/html` for automatic renewals.

## Security Hardening

- **Privilege separation**: `searchiwara` has `/usr/sbin/nologin` and write access only to the data and backup paths; application source remains owned by `root`.
- **`systemd` sandboxing**: Units enable `ProtectSystem=strict`, `ReadWritePaths=`, `ProtectHome=`, `PrivateTmp=true`, `PrivateDevices=true`, `NoNewPrivileges=true`, empty `CapabilityBoundingSet=`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, `SystemCallFilter=@system-service`, `MemoryDenyWriteExecute=true`, `ProtectKernel*`, `ProtectProc=invisible`, and `UMask=0027`. Inspect with `systemd-analyze security search-iwara-web.service`.
- **`nginx` & webhook guards**: `server_tokens off`, `16 KiB` body limit, per-IP rate limiting (`10 r/s` burst `20` on HTML routes, `20 r/s` burst `40` on `/api/`), loopback-only `/metrics`, TLS 1.2/1.3, HSTS, and security headers preserved on `/static/` responses. Alert webhooks reject `file://`, embedded credentials, cloud metadata IPs (`169.254.169.254`), and unsafe redirects.

## Health Checks, Metrics & Alerts

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Liveness check (`200` when the web process is up) |
| `GET /readyz` | Readiness check (`200` when SQLite is readable and at Schema v5, `503` otherwise) |
| `GET /metrics` | Prometheus metrics (request latency histograms, dataset counts, last sync status, request/retry/throttle counters) |

`/metrics` is loopback-only by default. When binding publicly or running in Docker, set `SEARCH_IWARA_METRICS_TOKEN` and configure Prometheus with `Authorization: Bearer <token>`.

[`deploy/prometheus/alerts.yml`](../deploy/prometheus/alerts.yml) defines five alert rules (`SearchIwaraDown`, `SearchIwaraSyncStale`, `SearchIwaraSyncFailed`, `SearchIwaraThrottled`, `SearchIwaraHighLatency`):

```bash
sudo install -m 0644 deploy/prometheus/alerts.yml /etc/prometheus/rules/search-iwara-alerts.yml
promtool check rules /etc/prometheus/rules/search-iwara-alerts.yml
```

## Backups & Restore

`search-iwara-backup.timer` runs daily at `04:00` (`+0`–`30 min` jitter) using SQLite's online backup API, verifies `PRAGMA quick_check` and free disk headroom before writing, and rotates older snapshots.

Restore procedure on a `systemd` host (for `.sqlite3.gz`; copy directly if uncompressed `.sqlite3`):

```bash
sudo systemctl stop search-iwara-web.service search-iwara-sync.timer
sudo sh -c 'gunzip -c /opt/search-iwara/data/backups/<backup-file>.sqlite3.gz > /opt/search-iwara/data/oreno3d.sqlite3'
sudo chown searchiwara:searchiwara /opt/search-iwara/data/oreno3d.sqlite3
sudo chmod 0640 /opt/search-iwara/data/oreno3d.sqlite3
sudo rm -f /opt/search-iwara/data/oreno3d.sqlite3-wal /opt/search-iwara/data/oreno3d.sqlite3-shm
sudo systemctl start search-iwara-web.service search-iwara-sync.timer
```

For common deployment issues, see [docs/troubleshooting.md](troubleshooting.md).
