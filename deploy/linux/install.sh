#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

APP_DIR="${REPO_ROOT}"
DB_PATH=""
SYNC_INTERVAL_HOURS="6"
WEB_HOST="127.0.0.1"
WEB_PORT="8000"
SERVICE_USER="${SUDO_USER:-$(id -un)}"
SERVICE_GROUP="$(id -gn "${SERVICE_USER}" 2>/dev/null || printf '%s' "${SERVICE_USER}")"
ENV_FILE="/etc/search-iwara/search-iwara.env"
SYSTEMD_DIR="/etc/systemd/system"
NGINX_AVAILABLE_DIR="/etc/nginx/sites-available"
NGINX_ENABLED_DIR="/etc/nginx/sites-enabled"
ENABLE_NGINX="1"
UV_BIN="$(command -v uv || true)"

usage() {
  cat <<'EOF'
Usage: sudo ./deploy/linux/install.sh [options]

Options:
  --sync-hours HOURS           Run sync latest every N hours. Default: 6.
  --app-dir PATH               Repo/app directory. Default: current repo root.
  --db-path PATH               SQLite path. Default: APP_DIR/data/oreno3d.sqlite3.
  --user USER                  systemd service user. Default: invoking user.
  --group GROUP                systemd service group. Default: user's primary group.
  --web-host HOST              App bind host. Default: 127.0.0.1.
  --web-port PORT              App bind port. Default: 8000.
  --env-file PATH              Environment file path. Default: /etc/search-iwara/search-iwara.env.
  --systemd-dir PATH           systemd unit directory. Default: /etc/systemd/system.
  --nginx-available-dir PATH   nginx sites-available dir. Default: /etc/nginx/sites-available.
  --nginx-enabled-dir PATH     nginx sites-enabled dir. Default: /etc/nginx/sites-enabled.
  --skip-nginx                 Install only systemd units; no nginx config.
  -h, --help                   Show this help.
EOF
}

err() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "run this installer with sudo or as root"
  fi
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    err "required command not found: $1"
  fi
}

escape_sed() {
  printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

render_template() {
  local src="$1"
  local dest="$2"
  sed \
    -e "s/__APP_DIR__/$(escape_sed "${APP_DIR}")/g" \
    -e "s/__ENV_FILE__/$(escape_sed "${ENV_FILE}")/g" \
    -e "s/__SERVICE_USER__/$(escape_sed "${SERVICE_USER}")/g" \
    -e "s/__SERVICE_GROUP__/$(escape_sed "${SERVICE_GROUP}")/g" \
    -e "s/__SYNC_INTERVAL_HOURS__/$(escape_sed "${SYNC_INTERVAL_HOURS}")/g" \
    -e "s/__UPSTREAM_HOST__/$(escape_sed "${WEB_HOST}")/g" \
    -e "s/__UPSTREAM_PORT__/$(escape_sed "${WEB_PORT}")/g" \
    "${src}" > "${dest}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sync-hours)
      SYNC_INTERVAL_HOURS="$2"
      shift 2
      ;;
    --app-dir)
      APP_DIR="$2"
      shift 2
      ;;
    --db-path)
      DB_PATH="$2"
      shift 2
      ;;
    --user)
      SERVICE_USER="$2"
      shift 2
      ;;
    --group)
      SERVICE_GROUP="$2"
      shift 2
      ;;
    --web-host)
      WEB_HOST="$2"
      shift 2
      ;;
    --web-port)
      WEB_PORT="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --systemd-dir)
      SYSTEMD_DIR="$2"
      shift 2
      ;;
    --nginx-available-dir)
      NGINX_AVAILABLE_DIR="$2"
      shift 2
      ;;
    --nginx-enabled-dir)
      NGINX_ENABLED_DIR="$2"
      shift 2
      ;;
    --skip-nginx)
      ENABLE_NGINX="0"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      err "unknown argument: $1"
      ;;
  esac
done

require_root
require_cmd systemctl
[[ -n "${UV_BIN}" ]] || err "uv is not installed or not on PATH"
[[ "${SYNC_INTERVAL_HOURS}" =~ ^[1-9][0-9]*$ ]] || err "--sync-hours must be a positive integer"

if [[ -z "${DB_PATH}" ]]; then
  DB_PATH="${APP_DIR}/data/oreno3d.sqlite3"
fi

if [[ ! -f "${APP_DIR}/pyproject.toml" || ! -d "${APP_DIR}/search_iwara" ]]; then
  err "--app-dir must point at an existing search_iwara repo checkout"
fi

if [[ "${ENABLE_NGINX}" == "1" ]]; then
  require_cmd nginx
fi

mkdir -p "$(dirname -- "${ENV_FILE}")" "${SYSTEMD_DIR}"
if [[ "${ENABLE_NGINX}" == "1" ]]; then
  mkdir -p "${NGINX_AVAILABLE_DIR}" "${NGINX_ENABLED_DIR}"
fi

cat > "${ENV_FILE}" <<EOF
APP_DIR=${APP_DIR}
UV_BIN=${UV_BIN}
SEARCH_IWARA_DB=${DB_PATH}
SEARCH_IWARA_HOST=${WEB_HOST}
SEARCH_IWARA_PORT=${WEB_PORT}
SEARCH_IWARA_STABLE_PAGES=3
SEARCH_IWARA_MAX_PAGES=
SEARCH_IWARA_REQUEST_CONCURRENCY=12
SEARCH_IWARA_REQUEST_DELAY_MS=50
SEARCH_IWARA_LIST_PREFETCH_PAGES=8
SEARCH_IWARA_DETAIL_BATCH_SIZE=96
EOF
chmod 640 "${ENV_FILE}"

render_template \
  "${SCRIPT_DIR}/systemd/search-iwara-web.service.template" \
  "${SYSTEMD_DIR}/search-iwara-web.service"
render_template \
  "${SCRIPT_DIR}/systemd/search-iwara-sync.service.template" \
  "${SYSTEMD_DIR}/search-iwara-sync.service"
render_template \
  "${SCRIPT_DIR}/systemd/search-iwara-sync.timer.template" \
  "${SYSTEMD_DIR}/search-iwara-sync.timer"

if [[ "${ENABLE_NGINX}" == "1" ]]; then
  render_template \
    "${SCRIPT_DIR}/nginx/search-iwara.conf.template" \
    "${NGINX_AVAILABLE_DIR}/search-iwara.conf"
  ln -sfn \
    "${NGINX_AVAILABLE_DIR}/search-iwara.conf" \
    "${NGINX_ENABLED_DIR}/search-iwara.conf"
fi

systemctl daemon-reload
systemctl enable --now search-iwara-web.service
systemctl enable --now search-iwara-sync.timer

if [[ "${ENABLE_NGINX}" == "1" ]]; then
  nginx -t
  systemctl reload nginx
fi

cat <<EOF
Installed Search Iwara Linux deployment.

App directory: ${APP_DIR}
Environment file: ${ENV_FILE}
Web service: search-iwara-web.service
Sync timer: search-iwara-sync.timer (every ${SYNC_INTERVAL_HOURS} hour(s))
EOF

if [[ "${ENABLE_NGINX}" == "1" ]]; then
  cat <<EOF
nginx site: ${NGINX_AVAILABLE_DIR}/search-iwara.conf

Next step:
  update server_name and TLS in ${NGINX_AVAILABLE_DIR}/search-iwara.conf for your domain.
EOF
else
  cat <<EOF
nginx was skipped. If you want direct public access, make sure:
  - SEARCH_IWARA_HOST is set to 0.0.0.0 in ${ENV_FILE}
  - your firewall allows TCP ${WEB_PORT}
EOF
fi
