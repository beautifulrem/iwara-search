#!/usr/bin/env bash
# Started by search-iwara-web.service. Runtime settings come from the env file.
set -euo pipefail
# shellcheck source=deploy/linux/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_app_bin

args=(
  serve
  --host "${SEARCH_IWARA_HOST:-127.0.0.1}"
  --port "${SEARCH_IWARA_PORT:-8000}"
  --proxy-headers
  --forwarded-allow-ips "${SEARCH_IWARA_FORWARDED_ALLOW_IPS:-127.0.0.1}"
)

exec "${SEARCH_IWARA_BIN}" "${args[@]}"
