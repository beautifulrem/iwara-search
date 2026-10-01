#!/usr/bin/env bash
# Started by search-iwara-backup.service: SQLite online backup with rotation.
set -euo pipefail
# shellcheck source=deploy/linux/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_app_bin

args=(db backup)
if [[ -n "${SEARCH_IWARA_BACKUP_DIR:-}" ]]; then
  args+=(--dest "${SEARCH_IWARA_BACKUP_DIR}")
fi
if [[ -n "${SEARCH_IWARA_BACKUP_KEEP:-}" ]]; then
  args+=(--keep "${SEARCH_IWARA_BACKUP_KEEP}")
fi

exec "${SEARCH_IWARA_BIN}" "${args[@]}"
