#!/bin/sh
# Daily `search-iwara db backup` (online SQLite backup + rotation) for the compose
# "backup" service. Failures are logged and retried the next day.
set -u

interval="${BACKUP_INTERVAL_SECONDS:-86400}"
jitter_max="${BACKUP_JITTER_SECONDS:-1800}"
sleep_pid=""

cleanup() {
  if [ -n "$sleep_pid" ]; then
    kill "$sleep_pid" 2>/dev/null || true
  fi
  exit 0
}
trap cleanup INT TERM

log() { printf 'backup-loop: %s\n' "$*" >&2; }
jitter() { python -c 'import random, sys; print(random.randint(0, max(0, int(sys.argv[1]))))' "$jitter_max"; }
sleep_interruptible() {
  seconds="$1"
  [ "$seconds" -le 0 ] && return 0
  sleep "$seconds" &
  sleep_pid=$!
  wait "$sleep_pid" 2>/dev/null || true
  sleep_pid=""
}

sleep_interruptible "$(jitter)"
while :; do
  search-iwara db backup
  code=$?
  [ "$code" -eq 0 ] || log "backup failed (exit ${code}); retrying next cycle"
  sleep_interruptible $((interval + $(jitter)))
done
