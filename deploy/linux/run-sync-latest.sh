#!/usr/bin/env bash
# Started by search-iwara-sync.service. Crawler settings (concurrency, rate,
# proxy, log format) are read by the app from SEARCH_IWARA_* variables; only
# the sync-latest specific options are mapped to CLI flags here.
# Exit codes: 0 ok, 1 too many failures, 2 parser drift, 75 lock held.
set -euo pipefail
# shellcheck source=deploy/linux/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_app_bin

args=(sync latest --stable-pages "${SEARCH_IWARA_STABLE_PAGES:-3}")
if [[ -n "${SEARCH_IWARA_MAX_PAGES:-}" ]]; then
  args+=(--max-pages "${SEARCH_IWARA_MAX_PAGES}")
fi

exec "${SEARCH_IWARA_BIN}" "${args[@]}"
