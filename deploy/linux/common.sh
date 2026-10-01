# shellcheck shell=bash
# Shared helpers for the run-*.sh wrappers. Sourced, not executed.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd -- "${SCRIPT_DIR}/../.." && pwd)}"
SEARCH_IWARA_BIN="${APP_DIR}/.venv/bin/search-iwara"

require_app_bin() {
  if [[ ! -x "${SEARCH_IWARA_BIN}" ]]; then
    # shellcheck disable=SC2016  # backticks are literal text in the message
    printf 'error: %s is missing. Run `sudo %s/deploy/linux/manage.py update` (or `uv sync --frozen --no-dev` in %s).\n' \
      "${SEARCH_IWARA_BIN}" "${APP_DIR}" "${APP_DIR}" >&2
    exit 1
  fi
}
