# Linux Deployment

This project now includes Linux deployment assets for:

- running the web UI under `systemd`
- running `sync latest` on a repeating timer
- exposing the app through `nginx` on an existing domain

The deployment assets live in [`deploy/linux`](/path/to/repo/deploy/linux).

For an interactive setup and maintenance flow, use:

```bash
sudo ./deploy/linux/manage.py
```

The manager script can:

- detect whether Search Iwara is already installed
- guide first-time installation with a deployment mode choice
- update runtime and sync defaults later
- run manual `sync latest` and `sync full`
- restart services and show system state

## What Gets Installed

- `search-iwara-web.service`
  - runs `uv run search-iwara serve`
- `search-iwara-sync.service`
  - runs `uv run search-iwara sync latest`
- `search-iwara-sync.timer`
  - triggers the sync service every N hours
- `search-iwara.conf`
  - nginx reverse proxy config for your domain
- `/etc/search-iwara/search-iwara.env`
  - runtime settings for host, port, db path, and sync options

## Prerequisites

- Linux host with `systemd`
- `uv` installed and available on `PATH`
- `nginx` installed if you want domain reverse proxy
- this repo already checked out on the server

## One-Command Install

From the repo root:

```bash
sudo ./deploy/linux/install.sh \
  --sync-hours 6
```

This will:

- write `/etc/search-iwara/search-iwara.env`
- install the `systemd` units into `/etc/systemd/system`
- enable and start the web service
- enable the sync timer
- auto-install `uv` if it is missing
- install and reload an nginx site config

If nginx mode is enabled and `nginx` is missing, the installer will also attempt to install it automatically using the system package manager.

The generated nginx config is intentionally generic and starts with:

```nginx
server_name _;
```

Edit it afterwards for your actual domain and TLS setup.

If you use the interactive manager instead, it can also write nginx config with:

- a chosen `server_name`
- HTTP-only mode
- HTTPS mode using existing cert/key paths

If you do not want nginx and only want the app bound directly to a public port:

```bash
sudo ./deploy/linux/install.sh \
  --skip-nginx \
  --web-host 0.0.0.0 \
  --web-port 8000
```

If the repo is checked out somewhere else, point `--app-dir` at that existing checkout:

```bash
sudo ./deploy/linux/install.sh \
  --sync-hours 6 \
  --app-dir /srv/search-iwara
```

## Change Sync Frequency

Re-run the installer with a different `--sync-hours` value:

```bash
sudo ./deploy/linux/install.sh \
  --sync-hours 2
```

The timer uses `OnUnitActiveSec=<hours>h`, so `--sync-hours 2` means "run every 2 hours".

## Runtime Settings

Main runtime settings are stored in:

```bash
/etc/search-iwara/search-iwara.env
```

Common fields:

```bash
SEARCH_IWARA_DB=/opt/search-iwara/data/oreno3d.sqlite3
SEARCH_IWARA_HOST=127.0.0.1
SEARCH_IWARA_PORT=8000
SEARCH_IWARA_STABLE_PAGES=3
SEARCH_IWARA_REQUEST_CONCURRENCY=12
SEARCH_IWARA_REQUEST_DELAY_MS=50
SEARCH_IWARA_LIST_PREFETCH_PAGES=8
SEARCH_IWARA_DETAIL_BATCH_SIZE=96
```

After editing the env file:

```bash
sudo systemctl restart search-iwara-web.service
sudo systemctl restart search-iwara-sync.service
```

## Logs and Status

Check status:

```bash
sudo systemctl status search-iwara-web.service
sudo systemctl status search-iwara-sync.timer
```

Follow logs:

```bash
sudo journalctl -u search-iwara-web.service -f
sudo journalctl -u search-iwara-sync.service -f
```

## TLS

The nginx template only configures HTTP reverse proxy. After install, add TLS with your normal certificate flow, for example:

```bash
sudo certbot --nginx -d search.example.com
```
