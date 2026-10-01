"""Deployment configuration: the ``DeployConfig`` model and the env file it is stored in.

The env file (``/etc/search-iwara/search-iwara.env``) is the single source of truth. It is
read by systemd (``EnvironmentFile=``) for the app and by this manager for re-rendering.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Final

from . import shell

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
MANAGED_MARKER: Final = "Rendered by deploy/linux/manage.py"
DEFAULT_SERVICE_ACCOUNT: Final = "searchiwara"
WEB_UNIT: Final = "search-iwara-web.service"

DEPLOY_MODES: Final = ("nginx", "public", "local")
TLS_MODES: Final = ("http", "https")
LOG_FORMATS: Final = ("text", "json")
LOG_LEVELS: Final = ("DEBUG", "INFO", "WARNING", "ERROR")
LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1"})
PUBLIC_HOST: Final = "0.0.0.0"  # noqa: S104 - the "public" deploy mode binds all interfaces on purpose

LEGACY_ENV_KEYS: Final = ("SEARCH_IWARA_REQUEST_DELAY_MS", "SEARCH_IWARA_DETAIL_BATCH_SIZE")
LEGACY_DEFAULTS: Final = {"SEARCH_IWARA_REQUEST_CONCURRENCY": "12", "SEARCH_IWARA_LIST_PREFETCH_PAGES": "8"}


@dataclass(slots=True)
class DeployConfig:
    app_dir: str
    uv_bin: str
    db_path: str
    backup_dir: str
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    deploy_mode: str = "local"
    service_user: str = DEFAULT_SERVICE_ACCOUNT
    service_group: str = DEFAULT_SERVICE_ACCOUNT
    sync_hours: int = 6
    stable_pages: int = 3
    max_pages: str = ""
    request_concurrency: int = 4
    request_rate: float = 2.0
    list_prefetch_pages: int = 4
    proxy: str = ""
    trust_env: bool = True
    log_format: str = "json"
    log_level: str = "INFO"
    backup_keep: int = 7
    alert_webhook: str = ""
    metrics_token: str = ""
    api_docs_enabled: bool = False
    server_name: str = ""
    tls_mode: str = "http"
    tls_cert_file: str = ""
    tls_key_file: str = ""
    hsts_max_age: int = 63072000

    @property
    def data_dir(self) -> str:
        return str(Path(self.db_path).parent)

    @property
    def venv_bin(self) -> str:
        return str(Path(self.app_dir) / ".venv" / "bin" / "search-iwara")

    @property
    def metrics_exposed_publicly(self) -> bool:
        """The app port itself is reachable from outside (no nginx in front)."""
        return self.deploy_mode == "public" or self.web_host not in LOOPBACK_HOSTS


@dataclass(slots=True)
class Paths:
    env_file: Path
    systemd_dir: Path
    nginx_site: Path
    nginx_enabled: Path | None


# (env key, DeployConfig attribute). The order is the order written to the env file.
ENV_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("APP_DIR", "app_dir"),
    ("UV_BIN", "uv_bin"),
    ("SEARCH_IWARA_DB", "db_path"),
    ("SEARCH_IWARA_HOST", "web_host"),
    ("SEARCH_IWARA_PORT", "web_port"),
    ("SEARCH_IWARA_REQUEST_CONCURRENCY", "request_concurrency"),
    ("SEARCH_IWARA_REQUEST_RATE", "request_rate"),
    ("SEARCH_IWARA_LIST_PREFETCH_PAGES", "list_prefetch_pages"),
    ("SEARCH_IWARA_PROXY", "proxy"),
    ("SEARCH_IWARA_TRUST_ENV", "trust_env"),
    ("SEARCH_IWARA_LOG_FORMAT", "log_format"),
    ("SEARCH_IWARA_LOG_LEVEL", "log_level"),
    ("SEARCH_IWARA_BACKUP_DIR", "backup_dir"),
    ("SEARCH_IWARA_BACKUP_KEEP", "backup_keep"),
    ("SEARCH_IWARA_METRICS_TOKEN", "metrics_token"),
    ("SEARCH_IWARA_API_DOCS_ENABLED", "api_docs_enabled"),
    ("SEARCH_IWARA_STABLE_PAGES", "stable_pages"),
    ("SEARCH_IWARA_MAX_PAGES", "max_pages"),
    ("SEARCH_IWARA_ALERT_WEBHOOK", "alert_webhook"),
    ("SEARCH_IWARA_SYNC_HOURS", "sync_hours"),
    ("SEARCH_IWARA_DEPLOY_MODE", "deploy_mode"),
    ("SEARCH_IWARA_SERVICE_USER", "service_user"),
    ("SEARCH_IWARA_SERVICE_GROUP", "service_group"),
    ("SEARCH_IWARA_SERVER_NAME", "server_name"),
    ("SEARCH_IWARA_TLS_MODE", "tls_mode"),
    ("SEARCH_IWARA_TLS_CERT_FILE", "tls_cert_file"),
    ("SEARCH_IWARA_TLS_KEY_FILE", "tls_key_file"),
    ("SEARCH_IWARA_HSTS_MAX_AGE", "hsts_max_age"),
)

# Variables the app CLI reads (pydantic-settings); exported to manual runs from the menu.
RUNTIME_ENV_KEYS: Final = (
    "SEARCH_IWARA_DB",
    "SEARCH_IWARA_REQUEST_CONCURRENCY",
    "SEARCH_IWARA_REQUEST_RATE",
    "SEARCH_IWARA_LIST_PREFETCH_PAGES",
    "SEARCH_IWARA_PROXY",
    "SEARCH_IWARA_TRUST_ENV",
    "SEARCH_IWARA_LOG_FORMAT",
    "SEARCH_IWARA_LOG_LEVEL",
    "SEARCH_IWARA_BACKUP_DIR",
    "SEARCH_IWARA_BACKUP_KEEP",
)

_FIELD_TYPES: Final = {f.name: str(f.type) for f in fields(DeployConfig)}
# slots=True dataclasses do not keep defaults as class attributes.
FIELD_DEFAULTS: Final[dict[str, Any]] = {f.name: f.default for f in fields(DeployConfig)}
_SAFE_ENV_VALUE: Final = re.compile(r"[A-Za-z0-9_./:@%+,=-]*")
_ACCOUNT_NAME: Final = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
_TOKEN: Final = re.compile(r"[A-Za-z0-9_-]{16,256}")


# --- defaults -------------------------------------------------------------------------------


def find_existing_uv_bin() -> str:
    for candidate in ("/usr/local/bin/uv", "/usr/bin/uv"):
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("uv") or "/usr/local/bin/uv"


def default_config(app_dir: str | None = None) -> DeployConfig:
    root = Path(app_dir) if app_dir else REPO_ROOT
    db_path = root / "data" / "oreno3d.sqlite3"
    return DeployConfig(
        app_dir=str(root),
        uv_bin=find_existing_uv_bin(),
        db_path=str(db_path),
        backup_dir=str(db_path.parent / "backups"),
    )


def detect_nginx_layout() -> tuple[Path, Path | None]:
    """Debian-style sites-available/enabled, else RHEL-style conf.d."""
    if Path("/etc/nginx/sites-available").is_dir() or not Path("/etc/nginx/conf.d").is_dir():
        return (
            Path("/etc/nginx/sites-available/search-iwara.conf"),
            Path("/etc/nginx/sites-enabled/search-iwara.conf"),
        )
    return Path("/etc/nginx/conf.d/search-iwara.conf"), None


def default_paths() -> Paths:
    site, enabled = detect_nginx_layout()
    return Paths(
        env_file=Path("/etc/search-iwara/search-iwara.env"),
        systemd_dir=Path("/etc/systemd/system"),
        nginx_site=site,
        nginx_enabled=enabled,
    )


def new_metrics_token() -> str:
    return secrets.token_urlsafe(32)


def ensure_metrics_token(config: DeployConfig) -> bool:
    """Give a publicly reachable deployment a /metrics bearer token. Returns True if created."""
    if config.metrics_exposed_publicly and not config.metrics_token:
        config.metrics_token = new_metrics_token()
        return True
    return False


# --- env file format ------------------------------------------------------------------------


def format_env_value(value: str) -> str:
    if _SAFE_ENV_VALUE.fullmatch(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def parse_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return value


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = parse_env_value(value)
    return values


def to_env(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def from_env(attr: str, raw: str) -> Any:
    kind = _FIELD_TYPES[attr]
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "bool":
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return raw


def config_env_values(config: DeployConfig) -> dict[str, str]:
    return {key: to_env(getattr(config, attr)) for key, attr in ENV_FIELDS}


def render_env_file(config: DeployConfig) -> str:
    lines = [
        f"# {MANAGED_MARKER}; re-run manage.py to change values safely.",
        '# Empty optional values are kept as comments so they are not exported as "".',
    ]
    for key, value in config_env_values(config).items():
        lines.append(f"# {key}=" if value == "" else f"{key}={format_env_value(value)}")
    return "\n".join(lines) + "\n"


def write_env_file(path: Path, config: DeployConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 0600 root: systemd reads EnvironmentFile= before dropping privileges, and the file
    # holds secrets (alert webhook URL, metrics token).
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(render_env_file(config))
    path.chmod(0o600)


def migrate_legacy_env(values: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """Translate env files written by older releases (delay/batch-size era)."""
    migrated = dict(values)
    notes: list[str] = []
    if not values or "SEARCH_IWARA_REQUEST_RATE" in values:
        for key in LEGACY_ENV_KEYS:
            migrated.pop(key, None)
        return migrated, notes

    delay_raw = migrated.pop("SEARCH_IWARA_REQUEST_DELAY_MS", "")
    rate = float(FIELD_DEFAULTS["request_rate"])
    try:
        delay_ms = int(delay_raw) if delay_raw else 0
    except ValueError:
        delay_ms = 0
    if delay_ms > 0:
        rate = min(rate, round(1000 / delay_ms, 3))
    migrated["SEARCH_IWARA_REQUEST_RATE"] = to_env(rate)
    notes.append(
        f"SEARCH_IWARA_REQUEST_DELAY_MS={delay_raw or '(unset)'} replaced by SEARCH_IWARA_REQUEST_RATE={rate}"
    )

    if migrated.pop("SEARCH_IWARA_DETAIL_BATCH_SIZE", None) is not None:
        notes.append(
            "SEARCH_IWARA_DETAIL_BATCH_SIZE removed (detail fetches are now a bounded worker pipeline)"
        )

    new_defaults = {
        "SEARCH_IWARA_REQUEST_CONCURRENCY": FIELD_DEFAULTS["request_concurrency"],
        "SEARCH_IWARA_LIST_PREFETCH_PAGES": FIELD_DEFAULTS["list_prefetch_pages"],
    }
    for key, old_default in LEGACY_DEFAULTS.items():
        if migrated.get(key) == old_default:
            migrated[key] = str(new_defaults[key])
            notes.append(f"{key} {old_default} (old aggressive default) lowered to {new_defaults[key]}")
    return migrated, notes


def infer_deploy_mode(values: Mapping[str, str], paths: Paths) -> str:
    if paths.nginx_site.exists():
        return "nginx"
    if values.get("SEARCH_IWARA_HOST") == PUBLIC_HOST:
        return "public"
    return "local"


def load_config(paths: Paths | None = None) -> tuple[DeployConfig, list[str]]:
    paths = paths or default_paths()
    raw, notes = migrate_legacy_env(read_env_file(paths.env_file))
    config = default_config(raw.get("APP_DIR"))
    for key, attr in ENV_FIELDS:
        if raw.get(key, "") != "":
            setattr(config, attr, from_env(attr, raw[key]))
    if "SEARCH_IWARA_BACKUP_DIR" not in raw:
        config.backup_dir = str(Path(config.db_path).parent / "backups")
    if "SEARCH_IWARA_SERVICE_USER" not in raw:
        config.service_user = shell.systemctl_value(WEB_UNIT, "User") or DEFAULT_SERVICE_ACCOUNT
    if "SEARCH_IWARA_SERVICE_GROUP" not in raw:
        config.service_group = shell.systemctl_value(WEB_UNIT, "Group") or config.service_user
    if "SEARCH_IWARA_DEPLOY_MODE" not in raw:
        config.deploy_mode = infer_deploy_mode(raw, paths)
    return config, notes


def is_installed(paths: Paths) -> bool:
    return paths.env_file.exists() or (paths.systemd_dir / WEB_UNIT).exists()


# --- validation -----------------------------------------------------------------------------

Check = Callable[[DeployConfig], str | None]


def _require(condition: Callable[[DeployConfig], bool], message: str) -> Check:
    return lambda config: None if condition(config) else message


_CHECKS: Final[tuple[Check, ...]] = (
    _require(lambda c: c.deploy_mode in DEPLOY_MODES, f"deploy_mode must be one of {DEPLOY_MODES}"),
    _require(lambda c: c.tls_mode in TLS_MODES, f"tls_mode must be one of {TLS_MODES}"),
    _require(
        lambda c: (
            not (c.deploy_mode == "nginx" and c.tls_mode == "https")
            or bool(c.tls_cert_file and c.tls_key_file)
        ),
        "https mode needs tls_cert_file and tls_key_file",
    ),
    _require(lambda c: 1 <= c.sync_hours <= 24, "sync_hours must be between 1 and 24"),
    _require(lambda c: 1 <= c.web_port <= 65535, "web_port must be between 1 and 65535"),
    _require(lambda c: c.request_concurrency >= 1, "request_concurrency must be >= 1"),
    _require(lambda c: c.request_rate > 0, "request_rate must be > 0"),
    _require(lambda c: c.list_prefetch_pages >= 1, "list_prefetch_pages must be >= 1"),
    _require(lambda c: c.stable_pages >= 1, "stable_pages must be >= 1"),
    _require(
        lambda c: (
            not c.max_pages or (c.max_pages.isascii() and c.max_pages.isdigit() and int(c.max_pages) >= 1)
        ),
        "max_pages must be blank or a positive integer",
    ),
    _require(lambda c: c.backup_keep >= 1, "backup_keep must be >= 1"),
    _require(lambda c: c.hsts_max_age >= 0, "hsts_max_age must be >= 0"),
    _require(lambda c: c.log_format in LOG_FORMATS, f"log_format must be one of {LOG_FORMATS}"),
    _require(lambda c: c.log_level.upper() in LOG_LEVELS, f"log_level must be one of {LOG_LEVELS}"),
    _require(
        lambda c: not c.metrics_token or bool(_TOKEN.fullmatch(c.metrics_token)),
        "metrics_token must be 16-256 characters of [A-Za-z0-9_-]",
    ),
)


def validate_config(config: DeployConfig) -> list[str]:
    errors = [message for check in _CHECKS if (message := check(config))]
    errors += [
        f"invalid account name: {name!r}"
        for name in (config.service_user, config.service_group)
        if not _ACCOUNT_NAME.fullmatch(name)
    ]
    for label, value in (
        ("app_dir", config.app_dir),
        ("db_path", config.db_path),
        ("backup_dir", config.backup_dir),
    ):
        if not Path(value).is_absolute():
            errors.append(f"{label} must be an absolute path")
        if re.search(r"\s", value):
            errors.append(f"{label} must not contain whitespace (systemd path lists are space separated)")
    return errors
