"""Minimal systemd ``sd_notify`` / ``WatchdogSec`` integration using only stdlib + AnyIO.

When systemd starts ``search-iwara-web.service`` with ``WatchdogSec=``, it passes
``NOTIFY_SOCKET`` and ``WATCHDOG_USEC``. Rather than blindly pinging from a timer, the
watchdog runs a lightweight ``SELECT 1`` through the same ``anyio.to_thread`` limiter and
``ReadOnlyPool`` that serve HTTP requests. If the event loop, worker pool, or SQLite pool
wedges (for example under cgroup memory throttling), heartbeats stop and systemd restarts
the service automatically.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Mapping

import anyio
from anyio import to_thread

from ..storage import ReadOnlyPool

logger = logging.getLogger(__name__)


def sd_notify(state: str, *, env: Mapping[str, str] | None = None) -> bool:
    """Send a datagram to systemd's ``NOTIFY_SOCKET``; returns ``True`` when delivered."""

    source = os.environ if env is None else env
    raw_addr = source.get("NOTIFY_SOCKET", "").strip()
    if not raw_addr or not hasattr(socket, "AF_UNIX"):
        return False
    address: str | bytes = "\0" + raw_addr[1:] if raw_addr.startswith("@") else raw_addr
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(state.encode("utf-8"), address)
    except OSError as exc:
        logger.debug("sd_notify(%r) failed: %s", state, exc)
        return False
    return True


def watchdog_interval_seconds(
    *,
    env: Mapping[str, str] | None = None,
    pid: int | None = None,
) -> float | None:
    """Return the heartbeat period in seconds if systemd watchdog is active for this PID."""

    source = os.environ if env is None else env
    if not source.get("NOTIFY_SOCKET", "").strip():
        return None
    raw_usec = source.get("WATCHDOG_USEC", "").strip()
    if not raw_usec.isdecimal():
        return None
    usec = int(raw_usec)
    if usec <= 0:
        return None
    expected_pid = source.get("WATCHDOG_PID", "").strip()
    current_pid = os.getpid() if pid is None else pid
    if expected_pid and (not expected_pid.isdecimal() or int(expected_pid) != current_pid):
        return None
    return max(0.05, min(usec / 1_000_000 / 3.0, 20.0))


def _probe_pool(pool: ReadOnlyPool) -> bool:
    row = pool.get().execute("SELECT 1").fetchone()
    return row is not None and int(row[0]) == 1


async def run_watchdog(pool: ReadOnlyPool, interval: float, *, env: Mapping[str, str] | None = None) -> None:
    """Periodically verify worker-thread + SQLite liveness before sending ``WATCHDOG=1``."""

    timeout = max(0.1, interval * 2.0)
    while True:
        healthy = False
        try:
            with anyio.move_on_after(timeout):
                healthy = await to_thread.run_sync(_probe_pool, pool)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard: withhold heartbeat
            logger.warning("watchdog probe failed: %s", exc)
        if healthy:
            sd_notify("WATCHDOG=1", env=env)
        else:
            logger.error("watchdog probe timed out or failed; withholding WATCHDOG=1")
        await asyncio.sleep(interval)
