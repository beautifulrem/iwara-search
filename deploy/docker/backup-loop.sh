#!/bin/sh
# Daily `search-iwara db backup` (online SQLite backup + rotation) for the compose
# "backup" service. Failures are logged and retried the next day.
set -u

interval="${BACKUP_INTERVAL_SECONDS:-86400}"
jitter_max="${BACKUP_JITTER_SECONDS:-1800}"
sleep_pid=""
child_pid=""

cleanup() {
  if [ -n "$child_pid" ]; then
    kill -TERM "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
    child_pid=""
  fi
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
  case "${SEARCH_IWARA_BACKUP_COMPRESS:-true}" in
    0|false|FALSE|no|NO|off|OFF) compress_flag="--no-compress" ;;
    *) compress_flag="--compress" ;;
  esac
  search-iwara db backup "$compress_flag" &
  child_pid=$!
  wait "$child_pid"
  code=$?
  child_pid=""
  [ "$code" -eq 0 ] || log "backup failed (exit ${code}); retrying next cycle"
  sleep_interruptible $((interval + $(jitter)))
done
