"""Interactive questions. Pure input/validation; nothing here touches the system."""

from __future__ import annotations

from .config import PUBLIC_HOST, DeployConfig, ensure_metrics_token


def prompt_text(label: str, default: str = "", *, allow_blank: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default:
            return default
        if allow_blank:
            return ""
        print("Value required.")


def _parse_int(raw: str, minimum: int, maximum: int | None) -> int | str:
    """The parsed value, or an error message."""
    try:
        value = int(raw)
    except ValueError:
        return "Enter a whole number."
    if value < minimum or (maximum is not None and value > maximum):
        return (
            f"Value must be between {minimum} and {maximum}." if maximum else f"Value must be >= {minimum}."
        )
    return value


def prompt_int(label: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        if not raw:
            return default
        parsed = _parse_int(raw, minimum, maximum)
        if isinstance(parsed, int):
            return parsed
        print(parsed)


def prompt_optional_int(label: str, *, minimum: int = 1) -> int | None:
    while True:
        raw = input(f"{label}: ").strip()
        if not raw:
            return None
        parsed = _parse_int(raw, minimum, None)
        if isinstance(parsed, int):
            return parsed
        print(parsed)


def prompt_float(label: str, default: float, *, minimum: float = 0.01) -> float:
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            print("Enter a number.")
            continue
        if value < minimum:
            print(f"Value must be >= {minimum}.")
            continue
        return value


def prompt_choice(label: str, options: list[tuple[str, str]], default: str) -> str:
    print(label)
    for index, (_, text) in enumerate(options, start=1):
        print(f"  {index}) {text}")
    mapping = {str(index): key for index, (key, _) in enumerate(options, start=1)}
    reverse = {key: number for number, key in mapping.items()}
    while True:
        raw = input(f"Choose [{reverse.get(default, '1')}]: ").strip()
        if not raw:
            return default if default in reverse else options[0][0]
        if raw in mapping:
            return mapping[raw]
        print("Choose one of the listed numbers.")


def confirm(label: str, *, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} [{hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Answer yes or no.")


# --- configuration sections -----------------------------------------------------------------


def prompt_sync_settings(config: DeployConfig) -> None:
    config.sync_hours = prompt_int("Sync interval hours (1-24)", config.sync_hours, maximum=24)
    config.stable_pages = prompt_int("sync latest stable_pages", config.stable_pages)
    config.max_pages = prompt_text(
        "sync latest max_pages (blank for none)", config.max_pages, allow_blank=True
    )
    config.request_concurrency = prompt_int("Request concurrency", config.request_concurrency)
    config.request_rate = prompt_float("Request rate (requests/second)", config.request_rate)
    config.list_prefetch_pages = prompt_int("Listing prefetch pages", config.list_prefetch_pages)
    config.proxy = prompt_text("HTTP/SOCKS proxy URL (blank for none)", config.proxy, allow_blank=True)


def prompt_ops_settings(config: DeployConfig) -> None:
    config.backup_dir = prompt_text("Backup directory", config.backup_dir)
    config.backup_keep = prompt_int("Backups to keep", config.backup_keep)
    config.alert_webhook = prompt_text(
        "Failure alert webhook URL (blank = journal only)", config.alert_webhook, allow_blank=True
    )
    config.log_format = prompt_choice(
        "Log format", [("json", "JSON (journald / log shippers)"), ("text", "plain text")], config.log_format
    )
    config.api_docs_enabled = confirm("Serve the OpenAPI docs at /api/docs?", default=config.api_docs_enabled)


def _prompt_nginx(config: DeployConfig) -> None:
    config.web_host = "127.0.0.1"
    config.web_port = prompt_int("App port behind nginx", config.web_port, maximum=65535)
    config.server_name = prompt_text("nginx server_name / domain", config.server_name or "search.example.com")
    config.tls_mode = prompt_choice(
        "nginx TLS mode", [("http", "HTTP only"), ("https", "HTTPS with existing cert/key")], config.tls_mode
    )
    if config.tls_mode == "https":
        config.tls_cert_file = prompt_text(
            "TLS certificate file", config.tls_cert_file or "/etc/ssl/certs/search.example.com.pem"
        )
        config.tls_key_file = prompt_text(
            "TLS private key file", config.tls_key_file or "/etc/ssl/private/search.example.com.key"
        )
        config.hsts_max_age = prompt_int("HSTS max-age seconds (0 disables)", config.hsts_max_age, minimum=0)
    else:
        config.tls_cert_file = config.tls_key_file = ""


def _prompt_direct(config: DeployConfig, mode: str) -> None:
    config.web_host = PUBLIC_HOST if mode == "public" else "127.0.0.1"
    label = "Public bind port" if mode == "public" else "Local bind port"
    config.web_port = prompt_int(label, config.web_port, maximum=65535)
    config.server_name = config.tls_cert_file = config.tls_key_file = ""
    config.tls_mode = "http"
    if mode == "public":
        if ensure_metrics_token(config):
            print("Generated a bearer token for /metrics (SEARCH_IWARA_METRICS_TOKEN in the env file).")
        config.metrics_token = prompt_text("/metrics bearer token", config.metrics_token)


def prompt_install_settings(config: DeployConfig) -> DeployConfig:
    config.app_dir = prompt_text("App directory", config.app_dir)
    config.uv_bin = prompt_text("uv binary path", config.uv_bin)
    config.db_path = prompt_text("SQLite database path", config.db_path)
    config.service_user = prompt_text(
        "Service user (created as a system account if missing)", config.service_user
    )
    config.service_group = prompt_text("Service group", config.service_group)
    config.deploy_mode = prompt_choice(
        "Deployment mode",
        [
            ("nginx", "nginx reverse proxy on this server"),
            ("public", "direct public port"),
            ("local", "local-only / private upstream"),
        ],
        config.deploy_mode,
    )
    if config.deploy_mode == "nginx":
        _prompt_nginx(config)
    else:
        _prompt_direct(config, config.deploy_mode)
    prompt_sync_settings(config)
    prompt_ops_settings(config)
    return config


def prompt_sync_command_args(config: DeployConfig, *, full: bool) -> list[str]:
    concurrency = prompt_int("Request concurrency", config.request_concurrency)
    rate = prompt_float("Request rate (requests/second)", config.request_rate)
    args = ["--request-concurrency", str(concurrency), "--request-rate", str(rate)]
    if full:
        prefetch = prompt_int("List prefetch pages", config.list_prefetch_pages)
        args += ["--list-prefetch-pages", str(prefetch)]
        start_page = prompt_optional_int("Start page (blank = resume)")
        if start_page is not None:
            args += ["--start-page", str(start_page)]
        max_pages = prompt_optional_int("Max pages (blank = all)")
    else:
        stable_pages = prompt_int("Stable pages", config.stable_pages)
        args += ["--stable-pages", str(stable_pages)]
        max_pages = prompt_optional_int("Max pages (blank = none)")
    if max_pages is not None:
        args += ["--max-pages", str(max_pages)]
    return args
