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
import ipaddress
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

raw_url = os.environ["SEARCH_IWARA_ALERT_WEBHOOK"].strip()
parts = urllib.parse.urlsplit(raw_url)
host = (parts.hostname or "").lower()
is_loopback = host == "localhost"
ip_disallowed = False
if host and not is_loopback:
    try:
        ip_obj = ipaddress.ip_address(host)
        is_loopback = ip_obj.is_loopback
        ip_disallowed = (
            ip_obj.is_link_local
            or ip_obj.is_unspecified
            or ip_obj.is_multicast
            or (ip_obj.is_reserved and not ip_obj.is_loopback)
        )
    except ValueError:
        is_loopback = False
if (
    not host
    or parts.username
    or parts.password
    or ip_disallowed
    or (parts.scheme != "https" and not (parts.scheme == "http" and is_loopback))
):
    print(f"<3>search-iwara ALERT: refusing unsafe webhook URL scheme/host: {parts.scheme}://{host}")
    sys.exit(1)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: PLR0913, ANN001, ANN201
        raise urllib.error.HTTPError(req.full_url, code, f"refusing webhook redirect ({code})", headers, fp)


safe_url = urllib.parse.urlunsplit(
    (
        parts.scheme,
        parts.netloc,
        urllib.parse.quote(parts.path, safe="/:@!$&'()*+,;=-._~%"),
        urllib.parse.quote(parts.query, safe="=&/:@!$'()*+,;-._~%?"),
        "",
    )
)
payload = {
    "text": os.environ["ALERT_MESSAGE"],
    "unit": os.environ["ALERT_UNIT"],
    "host": os.environ["ALERT_HOST"],
    "result": os.environ["ALERT_RESULT"] or None,
    "exit_status": os.environ["ALERT_EXIT"] or None,
    "timestamp": int(time.time()),
}
request = urllib.request.Request(
    safe_url,
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "User-Agent": "search-iwara-alert"},
    method="POST",
)
opener = urllib.request.build_opener(_NoRedirectHandler)
try:
    with opener.open(request, timeout=10) as response:
        print(f"alert webhook delivered: HTTP {response.status}")
except Exception as exc:  # noqa: BLE001 - report any delivery failure to the journal
    print(f"<3>search-iwara ALERT: webhook delivery failed: {exc}")
    sys.exit(1)
PY
