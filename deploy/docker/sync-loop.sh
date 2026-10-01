#!/bin/sh
# Periodic `search-iwara sync latest` for the compose "sync" service.
#
# Exit codes of the sync (docs/configuration.md):
#   0 ok, 75 another sync holds the lock   -> sleep until the next cycle
#   1 finished with too many failures      -> logged, retried next cycle
#   2 parser drift (site markup changed)   -> stop syncing: write a marker file and exit 2
# While the drift marker exists for the *same* image version the service stays idle (and
# the container health check reports unhealthy); upgrading the image clears it.
set -u

interval="${SYNC_INTERVAL_SECONDS:-21600}"
jitter_max="${SYNC_JITTER_SECONDS:-600}"
marker="${SYNC_DRIFT_MARKER:-/data/.sync-parser-drift}"

log() { printf 'sync-loop: %s\n' "$*" >&2; }
jitter() { python -c 'import random, sys; print(random.randint(0, int(sys.argv[1])))' "$jitter_max"; }

version="$(search-iwara --version 2>/dev/null || echo unknown)"
if [ -f "$marker" ]; then
  if [ "$(cat "$marker")" = "$version" ]; then
    log "parser drift was detected with ${version}; not syncing until the image is upgraded" \
        "(or remove ${marker} after fixing the parser)"
    while :; do sleep 3600; done
  fi
  log "image changed since the parser drift (${version}); resuming"
  rm -f "$marker"
fi

sleep "$(jitter)"  # spread the first run so replicas/hosts do not align
while :; do
  search-iwara sync latest
  code=$?
  case "$code" in
    0 | 75) ;;
    1) log "sync finished with failures above tolerance (exit 1); retrying next cycle" ;;
    2)
      log "parser drift (exit 2): stopping; update the parser/image"
      printf '%s' "$version" > "$marker"
      exit 2
      ;;
    *) log "unexpected exit code ${code}; retrying next cycle" ;;
  esac
  sleep $((interval + $(jitter)))
done
