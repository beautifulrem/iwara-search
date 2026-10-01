#!/usr/bin/env bash
# Bootstrap installer for Search Iwara on a systemd Linux host.
#
# This script only prepares prerequisites (a pinned uv, nginx when needed) and
# then hands off to manage.py, which is the single source of truth for the
# service account, env file, systemd units, nginx site and DB migration.
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin:${PATH}"
umask 022

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Pinned uv release. Override with UV_VERSION=... or --uv-version.
UV_VERSION="${UV_VERSION:-0.12.19}"
# Optional: expected sha256 of the uv installer script for extra verification.
UV_INSTALLER_SHA256="${UV_INSTALLER_SHA256:-}"
# Keep uv-managed Python outside /root so the service account can execute it.
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/usr/local/share/search-iwara/python}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/var/cache/search-iwara/uv}"

ENV_FILE="/etc/search-iwara/search-iwara.env"
NGINX_WANTED="auto"
MANAGE_ARGS=()
UV_BIN=""
PACKAGE_MANAGER=""
PACKAGE_MANAGER_PREPARED="0"

usage() {
  cat <<'EOF'
Usage: sudo ./deploy/linux/install.sh [options]

Installs or reconfigures Search Iwara. Re-running is safe: values that are not
passed keep their current setting from the env file.

Options:
  --sync-hours HOURS           Run `sync latest` every N hours (1-24). Default: 6.
  --app-dir PATH               Repo/app directory. Default: this checkout.
  --db-path PATH               SQLite path. Default: APP_DIR/data/oreno3d.sqlite3.
  --backup-dir PATH            Backup directory. Default: <db dir>/backups.
  --user USER                  Service account (created if missing). Default: searchiwara.
  --group GROUP                Service group (created if missing). Default: searchiwara.
  --web-host HOST              App bind host. Default: 127.0.0.1.
  --web-port PORT              App bind port. Default: 8000.
  --server-name NAME           nginx server_name (domain). Default: _ (any).
  --tls-cert FILE              TLS certificate; with --tls-key enables HTTPS in nginx.
  --tls-key FILE               TLS private key.
  --hsts-max-age SECONDS       HSTS max-age for HTTPS (0 disables). Default: 63072000.
  --env-file PATH              Environment file. Default: /etc/search-iwara/search-iwara.env.
  --systemd-dir PATH           systemd unit directory. Default: /etc/systemd/system.
  --nginx-available-dir PATH   Directory for the nginx site file. Default: auto-detected.
  --nginx-enabled-dir PATH     Directory for the sites-enabled symlink. Default: auto-detected.
  --nginx                      Use the nginx reverse proxy (default on first install).
  --skip-nginx                 No nginx; the app binds --web-host/--web-port directly.
                               With a public --web-host a /metrics bearer token is generated.
  --metrics-token TOKEN        Bearer token required by /metrics (16+ chars of [A-Za-z0-9_-]).
  --api-docs | --no-api-docs   Serve / hide the OpenAPI docs at /api/docs. Default: hidden.
  --uv-version VERSION         uv release to install when uv is missing. Default: ${UV_VERSION}.
  -h, --help                   Show this help.
EOF
}

err() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || err "run this installer with sudo or as root"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || err "required command not found: $1"
}

detect_package_manager() {
  local candidate
  for candidate in apt-get dnf yum zypper pacman apk; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

install_packages() {
  if [[ -z "${PACKAGE_MANAGER}" ]]; then
    PACKAGE_MANAGER="$(detect_package_manager || true)"
    [[ -n "${PACKAGE_MANAGER}" ]] || err "no supported package manager found; install these manually: $*"
  fi
  case "${PACKAGE_MANAGER}" in
    apt-get)
      if [[ "${PACKAGE_MANAGER_PREPARED}" != "1" ]]; then
        apt-get update
        PACKAGE_MANAGER_PREPARED="1"
      fi
      DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
      ;;
    dnf) dnf install -y "$@" ;;
    yum) yum install -y "$@" ;;
    zypper) zypper --non-interactive install --no-confirm "$@" ;;
    pacman) pacman -Sy --noconfirm --needed "$@" ;;
    apk) apk add --no-cache "$@" ;;
    *) err "unsupported package manager: ${PACKAGE_MANAGER}" ;;
  esac
}

lookup_user_home() {
  command -v getent >/dev/null 2>&1 || err "getent is required to resolve the home directory of $1"
  getent passwd "$1" | cut -d: -f6
}

find_uv_bin() {
  local candidates=("/usr/local/bin/uv" "/usr/bin/uv")
  if [[ -n "${SUDO_USER:-}" ]]; then
    local sudo_home
    sudo_home="$(lookup_user_home "${SUDO_USER}")"
    [[ -n "${sudo_home}" ]] && candidates+=("${sudo_home}/.local/bin/uv")
  fi
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  command -v uv 2>/dev/null || return 1
}

download() {
  local url="$1" dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -fsSL "${url}" -o "${dest}"
  elif command -v wget >/dev/null 2>&1; then
    wget --https-only -qO "${dest}" "${url}"
  else
    install_packages curl ca-certificates
    curl --proto '=https' --tlsv1.2 -fsSL "${url}" -o "${dest}"
  fi
}

ensure_uv() {
  UV_BIN="$(find_uv_bin || true)"
  if [[ -n "${UV_BIN}" ]]; then
    printf 'Using uv at %s (%s)\n' "${UV_BIN}" "$("${UV_BIN}" --version)"
    return 0
  fi

  printf 'uv not found. Installing pinned uv %s to /usr/local/bin...\n' "${UV_VERSION}"
  local installer
  installer="$(mktemp)"
  # shellcheck disable=SC2064  # expand now: the path is fixed
  trap "rm -f -- '${installer}'" EXIT
  # Versioned installer URL: immutable for a given release. It verifies the
  # downloaded archive checksum itself; UV_INSTALLER_SHA256 pins the script too.
  download "https://astral.sh/uv/${UV_VERSION}/install.sh" "${installer}"
  if [[ -n "${UV_INSTALLER_SHA256}" ]]; then
    printf '%s  %s\n' "${UV_INSTALLER_SHA256}" "${installer}" | sha256sum -c - >/dev/null \
      || err "uv installer checksum mismatch"
  fi
  env UV_UNMANAGED_INSTALL="/usr/local/bin" sh "${installer}"

  UV_BIN="$(find_uv_bin || true)"
  [[ -n "${UV_BIN}" ]] || err "uv installation finished but no executable was found"
  "${UV_BIN}" --version | grep -q "${UV_VERSION}" || err "installed uv does not report version ${UV_VERSION}"
}

current_deploy_mode() {
  [[ -f "${ENV_FILE}" ]] || return 0
  sed -n 's/^SEARCH_IWARA_DEPLOY_MODE=//p' "${ENV_FILE}" | tail -n 1
}

ensure_nginx_if_needed() {
  local wanted="${NGINX_WANTED}"
  if [[ "${wanted}" == "auto" ]]; then
    local mode
    mode="$(current_deploy_mode)"
    # First install defaults to nginx; re-runs keep the recorded mode.
    [[ -z "${mode}" || "${mode}" == "nginx" ]] && wanted="1" || wanted="0"
  fi
  if [[ "${wanted}" == "1" ]] && ! command -v nginx >/dev/null 2>&1; then
    printf 'nginx not found. Installing nginx...\n'
    install_packages nginx
    require_cmd nginx
  fi
}

need_value() {
  [[ $# -ge 2 && -n "$2" ]] || err "$1 requires a value"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sync-hours|--app-dir|--db-path|--backup-dir|--user|--group|--web-host|--web-port|\
    --server-name|--tls-cert|--tls-key|--hsts-max-age|--systemd-dir|--metrics-token)
      need_value "$@"
      MANAGE_ARGS+=("$1" "$2")
      shift 2
      ;;
    --env-file)
      need_value "$@"
      ENV_FILE="$2"
      MANAGE_ARGS+=("$1" "$2")
      shift 2
      ;;
    --nginx-available-dir)
      need_value "$@"
      MANAGE_ARGS+=(--nginx-site "${2%/}/search-iwara.conf")
      shift 2
      ;;
    --nginx-enabled-dir)
      need_value "$@"
      MANAGE_ARGS+=(--nginx-enabled "${2%/}/search-iwara.conf")
      shift 2
      ;;
    --nginx)
      NGINX_WANTED="1"
      MANAGE_ARGS+=(--nginx)
      shift
      ;;
    --skip-nginx)
      NGINX_WANTED="0"
      MANAGE_ARGS+=(--skip-nginx)
      shift
      ;;
    --api-docs|--no-api-docs)
      MANAGE_ARGS+=("$1")
      shift
      ;;
    --uv-version)
      need_value "$@"
      UV_VERSION="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      err "unknown argument: $1 (see --help)"
      ;;
  esac
done

require_root
require_cmd systemctl
ensure_uv
ensure_nginx_if_needed

# manage.py only needs the standard library; uv provides a Python >= 3.13
# (downloading it into UV_PYTHON_INSTALL_DIR if the system has none).
"${UV_BIN}" run --no-project --python 3.13 python "${SCRIPT_DIR}/manage.py" \
  install --non-interactive --uv-bin "${UV_BIN}" "${MANAGE_ARGS[@]+"${MANAGE_ARGS[@]}"}"
