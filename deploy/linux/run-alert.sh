#!/usr/bin/env bash
# Started by search-iwara-alert@<unit>.service when a unit fails.
# Always writes an err-priority journal entry; additionally POSTs JSON to
# SEARCH_IWARA_ALERT_WEBHOOK when it is set (Slack/Discord/ntfy/Gotify-style).
set -euo pipefail
# shellcheck source=deploy/linux/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

unit="${1:?usage: run-alert.sh <failed-unit>}"
host="$(hostname 2>/dev/null || printf 'unknown-host')"
result="$(systemctl show -p Result --value "${unit}" 2>/dev/null || true)"
exit_status="$(systemctl show -p ExecMainStatus --value "${unit}" 2>/dev/null || true)"
message="search-iwara ALERT: ${unit} failed on ${host} (result=${result:-unknown}, exit=${exit_status:-unknown}). Inspect with: journalctl -u ${unit} -e"

# "<3>" = syslog err priority (SyslogLevelPrefix=true in the unit).
printf '<3>%s\n' "${message}"

if [[ -z "${SEARCH_IWARA_ALERT_WEBHOOK:-}" ]]; then
  exit 0
fi

python_bin="${APP_DIR}/.venv/bin/python"
if [[ ! -x "${python_bin}" ]]; then
  python_bin="$(command -v python3 || true)"
fi
if [[ -z "${python_bin}" ]]; then
  printf '<3>search-iwara ALERT: no python available to deliver the webhook\n'
  exit 1
fi

ALERT_UNIT="${unit}" ALERT_HOST="${host}" ALERT_RESULT="${result}" \
ALERT_EXIT="${exit_status}" ALERT_MESSAGE="${message}" \
exec "${python_bin}" - <<'PY'
import json
import os
import sys
import time
import urllib.request

payload = {
    "text": os.environ["ALERT_MESSAGE"],
    "unit": os.environ["ALERT_UNIT"],
    "host": os.environ["ALERT_HOST"],
    "result": os.environ["ALERT_RESULT"] or None,
    "exit_status": os.environ["ALERT_EXIT"] or None,
    "timestamp": int(time.time()),
}
request = urllib.request.Request(
    os.environ["SEARCH_IWARA_ALERT_WEBHOOK"],
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "User-Agent": "search-iwara-alert"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        print(f"alert webhook delivered: HTTP {response.status}")
except Exception as exc:  # noqa: BLE001 - report any delivery failure to the journal
    print(f"<3>search-iwara ALERT: webhook delivery failed: {exc}")
    sys.exit(1)
PY
