#!/usr/bin/env bash
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH}"

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
UV_BIN=""
PACKAGE_MANAGER=""
PACKAGE_MANAGER_PREPARED="0"

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

detect_package_manager() {
  local candidates=(apt-get dnf yum zypper pacman apk)
  local candidate
  for candidate in "${candidates[@]}"; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

prepare_package_manager() {
  if [[ -n "${PACKAGE_MANAGER}" ]]; then
    return 0
  fi
  PACKAGE_MANAGER="$(detect_package_manager || true)"
  [[ -n "${PACKAGE_MANAGER}" ]] || err "could not detect a supported package manager for automatic dependency installation"
}

install_packages() {
  prepare_package_manager
  case "${PACKAGE_MANAGER}" in
    apt-get)
      if [[ "${PACKAGE_MANAGER_PREPARED}" != "1" ]]; then
        apt-get update
        PACKAGE_MANAGER_PREPARED="1"
      fi
      DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
      ;;
    dnf)
      dnf install -y "$@"
      ;;
    yum)
      yum install -y "$@"
      ;;
    zypper)
      zypper --non-interactive install --no-confirm "$@"
      ;;
    pacman)
      pacman -Sy --noconfirm --needed "$@"
      ;;
    apk)
      apk add --no-cache "$@"
      ;;
    *)
      err "unsupported package manager: ${PACKAGE_MANAGER}"
      ;;
  esac
}

lookup_user_home() {
  local user="$1"
  if command -v getent >/dev/null 2>&1; then
    getent passwd "${user}" | cut -d: -f6
  else
    eval printf '%s' "~${user}"
  fi
}

find_uv_bin() {
  local candidates=("/usr/local/bin/uv" "/usr/bin/uv")
  if [[ -n "${SUDO_USER:-}" ]]; then
    local sudo_home
    sudo_home="$(lookup_user_home "${SUDO_USER}" || true)"
    if [[ -n "${sudo_home}" ]]; then
      candidates+=("${sudo_home}/.local/bin/uv")
    fi
  fi
  candidates+=("/root/.local/bin/uv")

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi
  return 1
}

ensure_download_client() {
  if command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1; then
    return 0
  fi
  printf 'Installing curl and CA certificates for uv bootstrap...\n'
  install_packages curl ca-certificates
}

ensure_uv() {
  UV_BIN="$(find_uv_bin || true)"
  if [[ -n "${UV_BIN}" ]]; then
    return 0
  fi

  printf 'uv not found. Installing uv system-wide to /usr/local/bin...\n'
  ensure_download_client

  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="/usr/local/bin" sh
  else
    wget -qO- https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="/usr/local/bin" sh
  fi

  UV_BIN="$(find_uv_bin || true)"
  [[ -n "${UV_BIN}" ]] || err "uv installation finished but no executable was found"
}

ensure_nginx() {
  if command -v nginx >/dev/null 2>&1; then
    return 0
  fi
  printf 'nginx not found. Installing nginx...\n'
  install_packages nginx
  require_cmd nginx
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
ensure_uv
[[ "${SYNC_INTERVAL_HOURS}" =~ ^[1-9][0-9]*$ ]] || err "--sync-hours must be a positive integer"

if [[ -z "${DB_PATH}" ]]; then
  DB_PATH="${APP_DIR}/data/oreno3d.sqlite3"
fi

if [[ ! -f "${APP_DIR}/pyproject.toml" || ! -d "${APP_DIR}/search_iwara" ]]; then
  err "--app-dir must point at an existing search_iwara repo checkout"
fi

if [[ "${ENABLE_NGINX}" == "1" ]]; then
  ensure_nginx
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
