"""Render systemd units and the nginx site from the templates next to this package."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from .config import MANAGED_MARKER, PUBLIC_HOST, WEB_UNIT, DeployConfig, Paths

TEMPLATE_ROOT: Final = Path(__file__).resolve().parent.parent
SYSTEMD_TEMPLATE_DIR: Final = TEMPLATE_ROOT / "systemd"
NGINX_TEMPLATE_DIR: Final = TEMPLATE_ROOT / "nginx"

SYNC_SERVICE: Final = "search-iwara-sync.service"
SYNC_TIMER: Final = "search-iwara-sync.timer"
BACKUP_SERVICE: Final = "search-iwara-backup.service"
BACKUP_TIMER: Final = "search-iwara-backup.timer"
ALERT_UNIT: Final = "search-iwara-alert@.service"
UNIT_TEMPLATES: Final[dict[str, str]] = {
    WEB_UNIT: "search-iwara-web.service.template",
    SYNC_SERVICE: "search-iwara-sync.service.template",
    SYNC_TIMER: "search-iwara-sync.timer.template",
    BACKUP_SERVICE: "search-iwara-backup.service.template",
    BACKUP_TIMER: "search-iwara-backup.timer.template",
    ALERT_UNIT: "search-iwara-alert@.service.template",
}
TIMER_UNITS: Final = (SYNC_TIMER, BACKUP_TIMER)
BACKUP_ON_CALENDAR: Final = "*-*-* 04:00:00"
HOME_PREFIXES: Final = ("/home", "/root", "/run/user")
HTTP2_DIRECTIVE_MIN_NGINX: Final = (1, 25, 1)
_PLACEHOLDER: Final = re.compile(r"__[A-Z0-9_]+__")


def render_template(path: Path, replacements: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(key, value)
    leftover = _PLACEHOLDER.findall(text)
    if leftover:
        raise ValueError(f"unrendered placeholders in {path.name}: {sorted(set(leftover))}")
    return text


# --- systemd --------------------------------------------------------------------------------


def sync_on_calendar(hours: int) -> str:
    if not 1 <= hours <= 24:
        raise ValueError("sync interval must be between 1 and 24 hours")
    if hours == 24:
        return "*-*-* 00:00:00"
    return f"*-*-* 0/{hours}:00:00"


def protect_home_mode(config: DeployConfig) -> str:
    """``ProtectHome=true`` hides /home entirely; fall back to read-only when the checkout
    or the data lives there (``ReadWritePaths=`` re-enables the data directory)."""
    for path in (config.app_dir, config.data_dir, config.backup_dir):
        if any(path == prefix or path.startswith(prefix + "/") for prefix in HOME_PREFIXES):
            return "read-only"
    return "true"


def read_write_paths(config: DeployConfig) -> str:
    paths = [config.data_dir]
    backup = config.backup_dir
    if not (backup == config.data_dir or backup.startswith(config.data_dir + "/")):
        paths.append(f"-{backup}")  # "-": do not fail the unit if the backup dir was removed
    return " ".join(paths)


def render_hardening(config: DeployConfig) -> str:
    return render_template(
        SYSTEMD_TEMPLATE_DIR / "hardening.conf.fragment",
        {"__PROTECT_HOME__": protect_home_mode(config), "__READ_WRITE_PATHS__": read_write_paths(config)},
    ).rstrip("\n")


def render_units(config: DeployConfig, paths: Paths) -> dict[str, str]:
    replacements = {
        "__MANAGED_MARKER__": MANAGED_MARKER,
        "__APP_DIR__": config.app_dir,
        "__DATA_DIR__": config.data_dir,
        "__ENV_FILE__": str(paths.env_file),
        "__SERVICE_USER__": config.service_user,
        "__SERVICE_GROUP__": config.service_group,
        "__SYNC_INTERVAL_HOURS__": str(config.sync_hours),
        "__SYNC_ON_CALENDAR__": sync_on_calendar(config.sync_hours),
        "__BACKUP_ON_CALENDAR__": BACKUP_ON_CALENDAR,
        "__HARDENING__": render_hardening(config),
    }
    return {
        unit: render_template(SYSTEMD_TEMPLATE_DIR / template, replacements)
        for unit, template in UNIT_TEMPLATES.items()
    }


# --- nginx ----------------------------------------------------------------------------------


def parse_nginx_version(output: str | None) -> tuple[int, ...] | None:
    match = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", output or "")
    return tuple(int(part) for part in match.groups()) if match else None


def upstream_host(host: str) -> str:
    if host in {PUBLIC_HOST, ""}:
        return "127.0.0.1"
    if host == "::":
        return "[::1]"
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def hsts_header(config: DeployConfig, indent: str) -> str:
    if config.tls_mode != "https" or config.hsts_max_age <= 0:
        return ""
    return (
        f'{indent}add_header Strict-Transport-Security "max-age={config.hsts_max_age}; '
        'includeSubDomains" always;\n'
    )


def is_catch_all(config: DeployConfig) -> bool:
    """No domain configured: the site must answer requests for any host (e.g. the bare IP)."""

    return config.server_name in {"", "_"}


def listen_directives(config: DeployConfig, nginx_version: tuple[int, ...] | None) -> str:
    if config.tls_mode != "https":
        # Without a domain the site must be nginx's default server, or the distribution's
        # "Welcome to nginx" site keeps answering requests for the IP address.
        default = " default_server" if is_catch_all(config) else ""
        return f"    listen 80{default};\n    listen [::]:80{default};"
    if nginx_version is None or nginx_version >= HTTP2_DIRECTIVE_MIN_NGINX:
        return "    listen 443 ssl;\n    listen [::]:443 ssl;\n    http2 on;"
    return "    listen 443 ssl http2;\n    listen [::]:443 ssl http2;"


def render_nginx_config(config: DeployConfig, nginx_version: tuple[int, ...] | None = None) -> str:
    server_body = render_template(
        NGINX_TEMPLATE_DIR / "server-common.conf.fragment",
        {
            "__APP_DIR__": config.app_dir,
            "__UPSTREAM__": f"{upstream_host(config.web_host)}:{config.web_port}",
            "__HSTS_HEADER__": hsts_header(config, "    "),
            "__HSTS_HEADER_NESTED__": hsts_header(config, "        "),
        },
    ).rstrip("\n")
    template = (
        "search-iwara-https.conf.template"
        if config.tls_mode == "https"
        else "search-iwara-http.conf.template"
    )
    http_context = (
        (NGINX_TEMPLATE_DIR / "http-context.conf.fragment").read_text(encoding="utf-8").rstrip("\n")
    )
    return render_template(
        NGINX_TEMPLATE_DIR / template,
        {
            "__MANAGED_MARKER__": MANAGED_MARKER,
            "__HTTP_CONTEXT__": http_context,
            "__LISTEN__": listen_directives(config, nginx_version),
            "__SERVER_NAME__": config.server_name or "_",
            "__TLS_CERT_FILE__": config.tls_cert_file,
            "__TLS_KEY_FILE__": config.tls_key_file,
            "__SERVER_COMMON__": server_body,
        },
    )
