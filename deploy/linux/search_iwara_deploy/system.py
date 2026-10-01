"""Apply a ``DeployConfig`` to the host: accounts, directories, venv, units, nginx."""

from __future__ import annotations

import grp
import os
import pwd
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Final

from . import shell
from .config import (
    MANAGED_MARKER,
    RUNTIME_ENV_KEYS,
    WEB_UNIT,
    DeployConfig,
    Paths,
    config_env_values,
    validate_config,
    write_env_file,
)
from .render import (
    BACKUP_SERVICE,
    SYNC_SERVICE,
    TIMER_UNITS,
    is_catch_all,
    parse_nginx_version,
    render_nginx_config,
    render_units,
    upstream_host,
)

# uv-managed Python and cache live outside /root so the unprivileged service account can
# execute the venv interpreter (the venv symlinks into this directory).
UV_PYTHON_INSTALL_DIR: Final = "/usr/local/share/search-iwara/python"
UV_CACHE_DIR: Final = "/var/cache/search-iwara/uv"

# Exit codes of `search-iwara sync ...` (docs/configuration.md "Exit codes").
SYNC_EXIT_MESSAGES: Final = {
    0: "sync finished successfully",
    1: "sync finished but the failure count exceeded the threshold; see the log above",
    2: "parser drift detected: the site's markup changed; the parser needs an update",
    75: "another sync is already running (lock held); nothing was done",
}


class DeployError(SystemExit):
    """A fatal, user-facing deployment error (exits with a message, no traceback)."""


# --- running app commands as the service account -------------------------------------------


def service_user_kwargs(config: DeployConfig) -> dict[str, Any]:
    """Drop to the service account, clearing root's supplementary groups."""
    return {"user": config.service_user, "group": config.service_group, "extra_groups": []}


def service_env(config: DeployConfig, *, interactive: bool = False) -> dict[str, str]:
    env = {"PATH": shell.SERVICE_PATH, "LANG": os.environ.get("LANG", "C.UTF-8"), "HOME": config.data_dir}
    values = config_env_values(config)
    env.update({key: values[key] for key in RUNTIME_ENV_KEYS if values[key]})
    if interactive:
        env["SEARCH_IWARA_LOG_FORMAT"] = "text"
    return env


def run_service_command(config: DeployConfig, args: list[str], *, interactive: bool = False) -> int:
    cmd = [config.venv_bin, *args]
    print("  $ " + " ".join(shlex.quote(part) for part in cmd))
    result = shell.run(
        cmd,
        cwd=config.data_dir,
        env=service_env(config, interactive=interactive),
        check=False,
        **service_user_kwargs(config),
    )
    return result.returncode


# --- host preparation ------------------------------------------------------------------------


def nologin_shell() -> str:
    for candidate in ("/usr/sbin/nologin", "/sbin/nologin"):
        if Path(candidate).exists():
            return candidate
    return "/bin/false"


def ensure_service_account(config: DeployConfig) -> None:
    group, user = config.service_group, config.service_user
    busybox = shell.which("useradd") is None and shell.which("adduser") is not None
    try:
        grp.getgrnam(group)
    except KeyError:
        shell.run(["addgroup", "-S", group] if busybox else ["groupadd", "--system", group])
        print(f"Created system group {group}")
    try:
        pwd.getpwnam(user)
    except KeyError:
        if busybox:
            cmd = [
                "adduser",
                "-S",
                "-D",
                "-H",
                "-h",
                config.data_dir,
                "-s",
                nologin_shell(),
                "-G",
                group,
                user,
            ]
        else:
            cmd = ["useradd", "--system", "--gid", group, "--home-dir", config.data_dir,
                   "--no-create-home", "--shell", nologin_shell(), user]  # fmt: skip
        shell.run(cmd)
        print(f"Created system user {user}")


def prepare_directories(config: DeployConfig) -> None:
    uid = pwd.getpwnam(config.service_user).pw_uid
    gid = grp.getgrnam(config.service_group).gr_gid
    for directory in (Path(config.data_dir), Path(config.backup_dir)):
        directory.mkdir(parents=True, exist_ok=True)
        os.chown(directory, uid, gid)
        directory.chmod(0o750)
    db = Path(config.db_path)
    for candidate in (db, Path(f"{db}-wal"), Path(f"{db}-shm"), *Path(config.backup_dir).glob("*")):
        if candidate.exists():
            os.chown(candidate, uid, gid)
    if Path(config.app_dir).stat().st_uid == uid:
        print(
            f"warning: {config.app_dir} is owned by {config.service_user}; the service could modify its "
            "own code. Prefer a root-owned checkout (e.g. /opt/search-iwara)."
        )


def sync_venv(config: DeployConfig) -> None:
    env = dict(os.environ)
    env.update(
        UV_PYTHON_INSTALL_DIR=UV_PYTHON_INSTALL_DIR,
        UV_CACHE_DIR=UV_CACHE_DIR,
        UV_LINK_MODE="copy",
        UV_PROJECT_ENVIRONMENT=str(Path(config.app_dir) / ".venv"),
    )
    shell.run([config.uv_bin, "sync", "--frozen", "--no-dev"], cwd=config.app_dir, env=env)
    if not Path(config.venv_bin).exists():
        raise DeployError(f"uv sync finished but {config.venv_bin} is missing")


def check_service_access(config: DeployConfig) -> None:
    probe = shell.run(["test", "-x", config.venv_bin], check=False, cwd="/", **service_user_kwargs(config))
    if probe.returncode != 0:
        print(
            f"warning: {config.service_user} cannot execute {config.venv_bin}. If the checkout lives "
            "under /home, its parent directories are usually 0750; move it to /opt/search-iwara or "
            "grant o+x on the parents."
        )


def migrate_database(config: DeployConfig) -> None:
    code = run_service_command(config, ["db", "migrate"])
    if code != 0:
        raise DeployError(f"database migration failed (exit {code})")


def write_units(config: DeployConfig, paths: Paths) -> None:
    paths.systemd_dir.mkdir(parents=True, exist_ok=True)
    for unit, text in render_units(config, paths).items():
        target = paths.systemd_dir / unit
        target.write_text(text, encoding="utf-8")
        target.chmod(0o644)


# --- nginx ----------------------------------------------------------------------------------


def is_managed_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    # Legacy (pre-marker) site files are recognised by name + proxy_pass.
    return MANAGED_MARKER in text or ("proxy_pass http://" in text and "search-iwara" in path.name)


def reload_nginx() -> None:
    shell.run(["nginx", "-t"])
    shell.run(["systemctl", "reload", "nginx"])


def remove_nginx_site(paths: Paths) -> None:
    removed = False
    for candidate in (paths.nginx_enabled, paths.nginx_site):
        if candidate is not None and (
            candidate.is_symlink() or (candidate.exists() and is_managed_file(candidate))
        ):
            candidate.unlink()
            removed = True
    if removed and shell.which("nginx"):
        reload_nginx()


def disable_stock_default_site(config: DeployConfig, paths: Paths) -> tuple[Path, Path] | None:
    """Debian/Ubuntu enable a "Welcome to nginx" default_server; in catch-all mode it would
    shadow this site. Disable it (only the sites-enabled link; the file stays for re-enabling).
    Returns (link, target) so a failed `nginx -t` can restore it."""

    if paths.nginx_enabled is None or not is_catch_all(config):
        return None
    link = paths.nginx_enabled.parent / "default"
    if not link.is_symlink():
        return None
    target = Path(os.readlink(link))
    if target.name != "default" or target.parent.name != "sites-available":
        return None  # someone else's site: leave it alone
    link.unlink()
    print(f"Disabled the distribution's default nginx site ({link}); re-enable with: ln -s {target} {link}")
    return link, target


def apply_nginx(config: DeployConfig, paths: Paths) -> None:
    if config.deploy_mode != "nginx":
        remove_nginx_site(paths)
        return
    if not shell.which("nginx"):
        raise DeployError(
            "nginx mode selected but nginx is not installed (install.sh installs it automatically)."
        )
    previous = paths.nginx_site.read_text(encoding="utf-8") if paths.nginx_site.exists() else None
    disabled_default = disable_stock_default_site(config, paths)
    paths.nginx_site.parent.mkdir(parents=True, exist_ok=True)
    version = parse_nginx_version(shell.nginx_version_output())
    paths.nginx_site.write_text(render_nginx_config(config, version), encoding="utf-8")
    if paths.nginx_enabled is not None:
        paths.nginx_enabled.parent.mkdir(parents=True, exist_ok=True)
        if paths.nginx_enabled.is_symlink() or paths.nginx_enabled.exists():
            paths.nginx_enabled.unlink()
        paths.nginx_enabled.symlink_to(paths.nginx_site)
    try:
        shell.run(["nginx", "-t"])
    except subprocess.CalledProcessError as exc:
        if previous is None:
            paths.nginx_site.unlink()
        else:
            paths.nginx_site.write_text(previous, encoding="utf-8")
        if disabled_default is not None:
            disabled_default[0].symlink_to(disabled_default[1])
        raise DeployError("nginx -t rejected the new site config; the previous config was restored.") from exc
    shell.run(["systemctl", "reload", "nginx"])


# --- orchestration --------------------------------------------------------------------------


def health_url(config: DeployConfig) -> str:
    return f"http://{upstream_host(config.web_host)}:{config.web_port}/healthz"


def wait_for_health(config: DeployConfig, attempts: int = 15) -> bool:
    url = health_url(config)
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - fixed http:// URL
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    return False


def apply_install(config: DeployConfig, paths: Paths) -> None:
    errors = validate_config(config)
    if errors:
        raise DeployError("invalid configuration:\n  - " + "\n  - ".join(errors))
    os.umask(0o022)
    ensure_service_account(config)
    prepare_directories(config)
    sync_venv(config)
    check_service_access(config)
    write_env_file(paths.env_file, config)
    write_units(config, paths)
    migrate_database(config)
    shell.run(["systemctl", "daemon-reload"])
    shell.run(["systemctl", "enable", WEB_UNIT, *TIMER_UNITS])
    shell.run(["systemctl", "restart", WEB_UNIT])
    shell.run(["systemctl", "restart", *TIMER_UNITS])
    apply_nginx(config, paths)
    if wait_for_health(config):
        print(f"Health check OK: {WEB_UNIT} answers /healthz")
    else:
        print(f"warning: /healthz did not answer yet; check `journalctl -u {WEB_UNIT} -e`")


def update_deployment(config: DeployConfig, paths: Paths) -> None:
    """git pull --ff-only -> uv sync -> migrate -> re-render units -> restart."""
    app_dir = Path(config.app_dir)
    if (app_dir / ".git").exists():
        owner = pwd.getpwuid(app_dir.stat().st_uid)
        git_kwargs: dict[str, Any] = {}
        if owner.pw_uid != 0:
            git_kwargs = {"user": owner.pw_name, "group": owner.pw_gid, "extra_groups": []}
        shell.run(
            ["git", "-C", str(app_dir), "pull", "--ff-only"],
            env={**os.environ, "HOME": owner.pw_dir},
            **git_kwargs,
        )
    else:
        print(f"{app_dir} is not a git checkout; skipping git pull.")
    apply_install(config, paths)


def backup_now(config: DeployConfig) -> int:
    code = run_service_command(
        config,
        ["db", "backup", "--dest", config.backup_dir, "--keep", str(config.backup_keep)],
        interactive=True,
    )
    print("Backup finished." if code == 0 else f"Backup failed (exit {code}).")
    return code


def restart_web() -> None:
    shell.run(["systemctl", "restart", WEB_UNIT])


# --- status ---------------------------------------------------------------------------------


def config_summary_rows(config: DeployConfig) -> list[tuple[str, str]]:
    rows = [
        ("mode", config.deploy_mode),
        ("app_dir", config.app_dir),
        ("db_path", config.db_path),
        ("backup_dir", f"{config.backup_dir} (keep {config.backup_keep})"),
        ("service account", f"{config.service_user}:{config.service_group}"),
        ("web", f"{config.web_host}:{config.web_port}"),
        (
            "sync",
            f"every {config.sync_hours}h, stable_pages={config.stable_pages}, "
            f"max_pages={config.max_pages or '(none)'}",
        ),
        (
            "crawler",
            f"concurrency={config.request_concurrency}, rate={config.request_rate}/s, "
            f"prefetch={config.list_prefetch_pages}",
        ),
        ("proxy", config.proxy or "(none)"),
        ("logging", f"{config.log_format} {config.log_level}"),
        ("alert webhook", "configured" if config.alert_webhook else "(journal only)"),
        ("metrics", metrics_access_summary(config)),
        ("api docs", "enabled" if config.api_docs_enabled else "disabled"),
    ]
    if config.deploy_mode == "nginx":
        rows += [("server_name", config.server_name or "_"), ("tls", config.tls_mode)]
        if config.tls_mode == "https":
            rows += [
                ("tls cert/key", f"{config.tls_cert_file} / {config.tls_key_file}"),
                ("hsts max-age", str(config.hsts_max_age)),
            ]
    return rows


def metrics_access_summary(config: DeployConfig) -> str:
    if config.metrics_token:
        return "bearer token required (SEARCH_IWARA_METRICS_TOKEN in the env file)"
    if config.metrics_exposed_publicly:
        return "disabled (public bind without a token)"
    return "loopback only" if config.deploy_mode != "nginx" else "loopback only (nginx denies remote access)"


def print_config_summary(config: DeployConfig) -> None:
    print("\nConfiguration")
    for label, value in config_summary_rows(config):
        print(f"  {label}: {value}")


def show_status(config: DeployConfig, paths: Paths) -> None:
    print_config_summary(config)
    print("\nServices")
    for unit in (WEB_UNIT, *TIMER_UNITS):
        active, enabled = shell.systemctl_state(unit)
        print(f"  {unit}: active={active} enabled={enabled}")
    for unit in (SYNC_SERVICE, BACKUP_SERVICE):
        print(f"  {unit}: last result={shell.systemctl_value(unit, 'Result') or 'unknown'}")
    print(f"  health: {'ok' if wait_for_health(config, attempts=1) else 'not answering'}")
    print(f"  env_file: {paths.env_file}")
    if config.deploy_mode == "nginx":
        print(f"  nginx_site: {paths.nginx_site}")
