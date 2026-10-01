"""Process helpers. Every subprocess the manager starts goes through this module.

Commands are always argument vectors (never a shell string) built from validated
configuration, which is why the bandit subprocess checks are silenced per call.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SERVICE_PATH = "/usr/local/bin:/usr/bin:/bin"


def run(
    cmd: list[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    capture: bool = False,
    check: bool = True,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` (an argv list, no shell); raises ``CalledProcessError`` when ``check``."""
    return subprocess.run(  # noqa: S603 - argv list from validated config, no shell
        cmd,
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env is not None else None,
        check=check,
        text=True,
        capture_output=capture,
        **kwargs,
    )


def which(program: str) -> str | None:
    return shutil.which(program)


def systemctl_value(unit: str, key: str) -> str:
    """``systemctl show -p KEY --value UNIT``; empty string when unavailable."""
    try:
        result = run(["systemctl", "show", "-p", key, "--value", unit], capture=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def systemctl_state(unit: str) -> tuple[str, str]:
    """(is-active, is-enabled) for ``unit``."""

    def query(verb: str, fallback: str) -> str:
        try:
            return run(["systemctl", verb, unit], capture=True).stdout.strip()
        except subprocess.CalledProcessError as exc:
            return (exc.stdout or "").strip() or fallback
        except FileNotFoundError:
            return "unknown"

    return query("is-active", "inactive"), query("is-enabled", "disabled")


def nginx_version_output() -> str | None:
    if not which("nginx"):
        return None
    try:
        result = run(["nginx", "-v"], capture=True, check=False)
    except OSError:
        return None
    return result.stderr + result.stdout
