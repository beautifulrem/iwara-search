#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd -- "${SCRIPT_DIR}/../.." && pwd)}"
UV_BIN="${UV_BIN:-uv}"

cmd=(
  "${UV_BIN}" run search-iwara sync latest
  --stable-pages "${SEARCH_IWARA_STABLE_PAGES:-3}"
)

if [[ -n "${SEARCH_IWARA_MAX_PAGES:-}" ]]; then
  cmd+=(--max-pages "${SEARCH_IWARA_MAX_PAGES}")
fi
if [[ -n "${SEARCH_IWARA_REQUEST_CONCURRENCY:-}" ]]; then
  cmd+=(--request-concurrency "${SEARCH_IWARA_REQUEST_CONCURRENCY}")
fi
if [[ -n "${SEARCH_IWARA_REQUEST_DELAY_MS:-}" ]]; then
  cmd+=(--request-delay-ms "${SEARCH_IWARA_REQUEST_DELAY_MS}")
fi
if [[ -n "${SEARCH_IWARA_LIST_PREFETCH_PAGES:-}" ]]; then
  cmd+=(--list-prefetch-pages "${SEARCH_IWARA_LIST_PREFETCH_PAGES}")
fi
if [[ -n "${SEARCH_IWARA_DETAIL_BATCH_SIZE:-}" ]]; then
  cmd+=(--detail-batch-size "${SEARCH_IWARA_DETAIL_BATCH_SIZE}")
fi

cd "${APP_DIR}"
exec "${cmd[@]}"
