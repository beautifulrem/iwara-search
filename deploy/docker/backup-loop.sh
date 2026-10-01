#!/bin/sh
# Daily `search-iwara db backup` (online SQLite backup + rotation) for the compose
# "backup" service. Failures are logged and retried the next day.
set -u

interval="${BACKUP_INTERVAL_SECONDS:-86400}"
jitter_max="${BACKUP_JITTER_SECONDS:-1800}"

log() { printf 'backup-loop: %s\n' "$*" >&2; }
jitter() { python -c 'import random, sys; print(random.randint(0, int(sys.argv[1])))' "$jitter_max"; }

sleep "$(jitter)"
while :; do
  search-iwara db backup
  code=$?
  [ "$code" -eq 0 ] || log "backup failed (exit ${code}); retrying next cycle"
  sleep $((interval + $(jitter)))
done
