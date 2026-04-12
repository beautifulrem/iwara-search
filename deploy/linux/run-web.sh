#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd -- "${SCRIPT_DIR}/../.." && pwd)}"
UV_BIN="${UV_BIN:-uv}"
SEARCH_IWARA_HOST="${SEARCH_IWARA_HOST:-127.0.0.1}"
SEARCH_IWARA_PORT="${SEARCH_IWARA_PORT:-8000}"

cd "${APP_DIR}"
exec "${UV_BIN}" run search-iwara serve --host "${SEARCH_IWARA_HOST}" --port "${SEARCH_IWARA_PORT}"
