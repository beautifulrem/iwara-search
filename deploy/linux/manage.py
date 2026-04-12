#!/usr/bin/env python3
from __future__ import annotations

import os
import pwd
import grp
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
INSTALL_SCRIPT = SCRIPT_DIR / "install.sh"
NGINX_HTTP_TEMPLATE = SCRIPT_DIR / "nginx" / "search-iwara-http.conf.template"
NGINX_HTTPS_TEMPLATE = SCRIPT_DIR / "nginx" / "search-iwara-https.conf.template"
DEFAULT_ENV_FILE = Path("/etc/search-iwara/search-iwara.env")
DEFAULT_NGINX_AVAILABLE = Path("/etc/nginx/sites-available/search-iwara.conf")
DEFAULT_NGINX_ENABLED = Path("/etc/nginx/sites-enabled/search-iwara.conf")
DEFAULT_WEB_UNIT = "search-iwara-web.service"
DEFAULT_SYNC_SERVICE = "search-iwara-sync.service"
DEFAULT_SYNC_TIMER = "search-iwara-sync.timer"


@dataclass(slots=True)
class DeployConfig:
    app_dir: str
    uv_bin: str
    db_path: str
    web_host: str
    web_port: int
    stable_pages: int
    max_pages: str
    request_concurrency: int
    request_delay_ms: int
    list_prefetch_pages: int
    detail_batch_size: int
    sync_hours: int
    deploy_mode: str
    service_user: str
    service_group: str
    server_name: str
    tls_mode: str
    tls_cert_file: str
    tls_key_file: str


def default_service_user() -> str:
    return os.environ.get("SUDO_USER") or pwd.getpwuid(os.getuid()).pw_name


def default_service_group(user: str) -> str:
    return grp.getgrgid(pwd.getpwnam(user).pw_gid).gr_name


def find_existing_uv_bin() -> str:
    candidates = ["/usr/local/bin/uv", "/usr/bin/uv"]
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            candidates.append(str(Path(pwd.getpwnam(sudo_user).pw_dir) / ".local" / "bin" / "uv"))
        except KeyError:
            pass
    candidates.append(str(Path.home() / ".local" / "bin" / "uv"))
    for candidate in candidates:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("uv") or "/usr/local/bin/uv"


def default_config() -> DeployConfig:
    user = default_service_user()
    return DeployConfig(
        app_dir=str(REPO_ROOT),
        uv_bin=find_existing_uv_bin(),
        db_path=str(REPO_ROOT / "data" / "oreno3d.sqlite3"),
        web_host="127.0.0.1",
        web_port=8000,
        stable_pages=3,
        max_pages="",
        request_concurrency=12,
        request_delay_ms=50,
        list_prefetch_pages=8,
        detail_batch_size=96,
        sync_hours=6,
        deploy_mode="local",
        service_user=user,
        service_group=default_service_group(user),
        server_name="",
        tls_mode="http",
        tls_cert_file="",
        tls_key_file="",
    )


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def write_env_file(path: Path, config: DeployConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "APP_DIR": config.app_dir,
        "UV_BIN": config.uv_bin,
        "SEARCH_IWARA_DB": config.db_path,
        "SEARCH_IWARA_HOST": config.web_host,
        "SEARCH_IWARA_PORT": str(config.web_port),
        "SEARCH_IWARA_STABLE_PAGES": str(config.stable_pages),
        "SEARCH_IWARA_MAX_PAGES": config.max_pages,
        "SEARCH_IWARA_REQUEST_CONCURRENCY": str(config.request_concurrency),
        "SEARCH_IWARA_REQUEST_DELAY_MS": str(config.request_delay_ms),
        "SEARCH_IWARA_LIST_PREFETCH_PAGES": str(config.list_prefetch_pages),
        "SEARCH_IWARA_DETAIL_BATCH_SIZE": str(config.detail_batch_size),
        "SEARCH_IWARA_SYNC_HOURS": str(config.sync_hours),
        "SEARCH_IWARA_DEPLOY_MODE": config.deploy_mode,
        "SEARCH_IWARA_SERVICE_USER": config.service_user,
        "SEARCH_IWARA_SERVICE_GROUP": config.service_group,
        "SEARCH_IWARA_SERVER_NAME": config.server_name,
        "SEARCH_IWARA_TLS_MODE": config.tls_mode,
        "SEARCH_IWARA_TLS_CERT_FILE": config.tls_cert_file,
        "SEARCH_IWARA_TLS_KEY_FILE": config.tls_key_file,
    }
    text = "".join(f"{key}={value}\n" for key, value in values.items())
    path.write_text(text, encoding="utf-8")
    path.chmod(0o640)


def service_unit_value(unit: str, key: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "show", "-p", key, unit],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    value = result.stdout.strip()
    if "=" not in value:
        return ""
    return value.split("=", 1)[1]


def load_config(path: Path = DEFAULT_ENV_FILE) -> DeployConfig:
    base = default_config()
    values = read_env_file(path)
    service_user = values.get("SEARCH_IWARA_SERVICE_USER") or service_unit_value(DEFAULT_WEB_UNIT, "User") or base.service_user
    service_group = values.get("SEARCH_IWARA_SERVICE_GROUP") or service_unit_value(DEFAULT_WEB_UNIT, "Group") or default_service_group(service_user)
    return DeployConfig(
        app_dir=values.get("APP_DIR", base.app_dir),
        uv_bin=values.get("UV_BIN", base.uv_bin),
        db_path=values.get("SEARCH_IWARA_DB", base.db_path),
        web_host=values.get("SEARCH_IWARA_HOST", base.web_host),
        web_port=int(values.get("SEARCH_IWARA_PORT", str(base.web_port))),
        stable_pages=int(values.get("SEARCH_IWARA_STABLE_PAGES", str(base.stable_pages))),
        max_pages=values.get("SEARCH_IWARA_MAX_PAGES", base.max_pages),
        request_concurrency=int(values.get("SEARCH_IWARA_REQUEST_CONCURRENCY", str(base.request_concurrency))),
        request_delay_ms=int(values.get("SEARCH_IWARA_REQUEST_DELAY_MS", str(base.request_delay_ms))),
        list_prefetch_pages=int(values.get("SEARCH_IWARA_LIST_PREFETCH_PAGES", str(base.list_prefetch_pages))),
        detail_batch_size=int(values.get("SEARCH_IWARA_DETAIL_BATCH_SIZE", str(base.detail_batch_size))),
        sync_hours=int(values.get("SEARCH_IWARA_SYNC_HOURS", str(base.sync_hours))),
        deploy_mode=values.get("SEARCH_IWARA_DEPLOY_MODE", infer_deploy_mode(values, path)),
        service_user=service_user,
        service_group=service_group,
        server_name=values.get("SEARCH_IWARA_SERVER_NAME", ""),
        tls_mode=values.get("SEARCH_IWARA_TLS_MODE", "http"),
        tls_cert_file=values.get("SEARCH_IWARA_TLS_CERT_FILE", ""),
        tls_key_file=values.get("SEARCH_IWARA_TLS_KEY_FILE", ""),
    )


def infer_deploy_mode(values: dict[str, str], env_path: Path) -> str:
    host = values.get("SEARCH_IWARA_HOST", "127.0.0.1")
    if DEFAULT_NGINX_ENABLED.exists() or DEFAULT_NGINX_AVAILABLE.exists():
        return "nginx"
    if host == "0.0.0.0":
        return "public"
    if env_path.exists():
        return "local"
    return default_config().deploy_mode


def is_installed(path: Path = DEFAULT_ENV_FILE) -> bool:
    return path.exists() or Path("/etc/systemd/system/search-iwara-web.service").exists()


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Run this script with sudo or as root.")


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


def prompt_int(label: str, default: int, *, minimum: int = 1, allow_blank: bool = False) -> int | None:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{label}{suffix}: ").strip()
        if not raw:
            if allow_blank:
                return None
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Enter a whole number.")
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
    reverse = {key: str(index) for index, (key, _) in enumerate(options, start=1)}
    while True:
        raw = input(f"Choose [{reverse[default]}]: ").strip()
        if not raw:
            return default
        if raw in mapping:
            return mapping[raw]
        print("Choose one of the listed numbers.")


def confirm(label: str, default: bool = True) -> bool:
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


def print_config_summary(config: DeployConfig) -> None:
    print("\nConfiguration")
    print(f"  mode: {config.deploy_mode}")
    print(f"  app_dir: {config.app_dir}")
    print(f"  db_path: {config.db_path}")
    print(f"  service_user: {config.service_user}")
    print(f"  service_group: {config.service_group}")
    print(f"  web: {config.web_host}:{config.web_port}")
    print(f"  sync every: {config.sync_hours} hour(s)")
    print(f"  sync latest stable_pages: {config.stable_pages}")
    print(f"  sync latest max_pages: {config.max_pages or '(none)'}")
    print(f"  concurrency: {config.request_concurrency}")
    print(f"  request_delay_ms: {config.request_delay_ms}")
    print(f"  list_prefetch_pages: {config.list_prefetch_pages}")
    print(f"  detail_batch_size: {config.detail_batch_size}")
    if config.deploy_mode == "nginx":
        print(f"  server_name: {config.server_name}")
        print(f"  tls_mode: {config.tls_mode}")
        if config.tls_mode == "https":
            print(f"  tls_cert_file: {config.tls_cert_file}")
            print(f"  tls_key_file: {config.tls_key_file}")


def prompt_sync_settings(config: DeployConfig) -> None:
    config.sync_hours = prompt_int("Sync interval hours", config.sync_hours)
    config.stable_pages = prompt_int("sync latest stable_pages", config.stable_pages)
    max_pages = prompt_text("sync latest max_pages (blank for none)", config.max_pages, allow_blank=True)
    config.max_pages = max_pages
    config.request_concurrency = prompt_int("Request concurrency", config.request_concurrency)
    config.request_delay_ms = prompt_int("Request delay ms", config.request_delay_ms, minimum=0) or 0
    config.list_prefetch_pages = prompt_int("Listing prefetch pages", config.list_prefetch_pages)
    config.detail_batch_size = prompt_int("Detail batch size", config.detail_batch_size)


def prompt_install_settings(config: DeployConfig) -> DeployConfig:
    config.app_dir = prompt_text("App directory", config.app_dir)
    config.uv_bin = prompt_text("uv binary path", config.uv_bin)
    config.db_path = prompt_text("SQLite database path", config.db_path)
    config.service_user = prompt_text("Service user", config.service_user)
    config.service_group = prompt_text("Service group", config.service_group)
    mode = prompt_choice(
        "Deployment mode",
        [
            ("nginx", "nginx reverse proxy on this server"),
            ("public", "direct public port"),
            ("local", "local-only / private upstream"),
        ],
        config.deploy_mode,
    )
    config.deploy_mode = mode
    if mode == "nginx":
        config.web_host = "127.0.0.1"
        config.web_port = prompt_int("App port behind nginx", config.web_port)
        config.server_name = prompt_text("nginx server_name / domain", config.server_name or "search.example.com")
        config.tls_mode = prompt_choice(
            "nginx TLS mode",
            [("http", "HTTP only"), ("https", "HTTPS with existing cert/key")],
            config.tls_mode,
        )
        if config.tls_mode == "https":
            config.tls_cert_file = prompt_text("TLS certificate file", config.tls_cert_file or "/etc/ssl/certs/search.example.com.pem")
            config.tls_key_file = prompt_text("TLS private key file", config.tls_key_file or "/etc/ssl/private/search.example.com.key")
        else:
            config.tls_cert_file = ""
            config.tls_key_file = ""
    elif mode == "public":
        config.web_host = "0.0.0.0"
        config.web_port = prompt_int("Public bind port", config.web_port)
        config.server_name = ""
        config.tls_mode = "http"
        config.tls_cert_file = ""
        config.tls_key_file = ""
    else:
        config.web_host = "127.0.0.1"
        config.web_port = prompt_int("Local bind port", config.web_port)
        config.server_name = ""
        config.tls_mode = "http"
        config.tls_cert_file = ""
        config.tls_key_file = ""
    prompt_sync_settings(config)
    return config


def render_template(path: Path, replacements: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def render_nginx_config(config: DeployConfig) -> str:
    if config.tls_mode == "https":
        template = NGINX_HTTPS_TEMPLATE
    else:
        template = NGINX_HTTP_TEMPLATE
    return render_template(
        template,
        {
            "__SERVER_NAME__": config.server_name or "_",
            "__UPSTREAM_HOST__": config.web_host,
            "__UPSTREAM_PORT__": str(config.web_port),
            "__TLS_CERT_FILE__": config.tls_cert_file,
            "__TLS_KEY_FILE__": config.tls_key_file,
        },
    )


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        check=True,
        text=True,
        capture_output=capture,
    )


def install_or_update(config: DeployConfig) -> None:
    cmd = [
        "bash",
        str(INSTALL_SCRIPT),
        "--sync-hours",
        str(config.sync_hours),
        "--app-dir",
        config.app_dir,
        "--db-path",
        config.db_path,
        "--user",
        config.service_user,
        "--group",
        config.service_group,
        "--web-host",
        config.web_host,
        "--web-port",
        str(config.web_port),
    ]
    if config.deploy_mode != "nginx":
        cmd.append("--skip-nginx")
    run(cmd, cwd=REPO_ROOT)

    write_env_file(DEFAULT_ENV_FILE, config)

    if config.deploy_mode == "nginx":
        DEFAULT_NGINX_AVAILABLE.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_NGINX_AVAILABLE.write_text(render_nginx_config(config), encoding="utf-8")
        DEFAULT_NGINX_ENABLED.parent.mkdir(parents=True, exist_ok=True)
        if DEFAULT_NGINX_ENABLED.is_symlink() or DEFAULT_NGINX_ENABLED.exists():
            DEFAULT_NGINX_ENABLED.unlink()
        DEFAULT_NGINX_ENABLED.symlink_to(DEFAULT_NGINX_AVAILABLE)
        run(["nginx", "-t"])
        run(["systemctl", "reload", "nginx"])
    else:
        if DEFAULT_NGINX_ENABLED.is_symlink() or DEFAULT_NGINX_ENABLED.exists():
            DEFAULT_NGINX_ENABLED.unlink()
            if shutil.which("nginx"):
                run(["nginx", "-t"])
                run(["systemctl", "reload", "nginx"])

    run(["systemctl", "restart", DEFAULT_WEB_UNIT])


def systemctl_state(unit: str) -> tuple[str, str]:
    active = "unknown"
    enabled = "unknown"
    try:
        active = run(["systemctl", "is-active", unit], capture=True).stdout.strip()
    except subprocess.CalledProcessError as exc:
        active = exc.stdout.strip() or exc.stderr.strip() or "inactive"
    try:
        enabled = run(["systemctl", "is-enabled", unit], capture=True).stdout.strip()
    except subprocess.CalledProcessError as exc:
        enabled = exc.stdout.strip() or exc.stderr.strip() or "disabled"
    return active, enabled


def show_status(config: DeployConfig) -> None:
    print()
    print_config_summary(config)
    web_active, web_enabled = systemctl_state(DEFAULT_WEB_UNIT)
    timer_active, timer_enabled = systemctl_state(DEFAULT_SYNC_TIMER)
    print("\nServices")
    print(f"  {DEFAULT_WEB_UNIT}: active={web_active} enabled={web_enabled}")
    print(f"  {DEFAULT_SYNC_TIMER}: active={timer_active} enabled={timer_enabled}")
    print(f"  env_file: {DEFAULT_ENV_FILE}")
    if config.deploy_mode == "nginx":
        print(f"  nginx_conf: {DEFAULT_NGINX_AVAILABLE}")


def env_for_sync(config: DeployConfig) -> dict[str, str]:
    env = os.environ.copy()
    env["SEARCH_IWARA_DB"] = config.db_path
    return env


def demote(user: str, group: str) -> Callable[[], None]:
    pw = pwd.getpwnam(user)
    gr = grp.getgrnam(group)

    def inner() -> None:
        os.setgid(gr.gr_gid)
        os.setuid(pw.pw_uid)

    return inner


def run_as_service_user(config: DeployConfig, cmd: list[str]) -> None:
    env = env_for_sync(config)
    uv_bin = config.uv_bin if Path(config.uv_bin).exists() else find_existing_uv_bin()
    cmd = [uv_bin if part == config.uv_bin else part for part in cmd]
    subprocess.run(
        cmd,
        cwd=config.app_dir,
        env=env,
        check=True,
        text=True,
        preexec_fn=demote(config.service_user, config.service_group),
    )


def prompt_sync_command_args(config: DeployConfig, *, full: bool) -> list[str]:
    request_concurrency = prompt_int("Request concurrency override", config.request_concurrency)
    request_delay_ms = prompt_int("Request delay ms override", config.request_delay_ms, minimum=0) or 0
    list_prefetch_pages = prompt_int("List prefetch pages override", config.list_prefetch_pages)
    detail_batch_size = prompt_int("Detail batch size override", config.detail_batch_size)

    args = [
        "--request-concurrency",
        str(request_concurrency),
        "--request-delay-ms",
        str(request_delay_ms),
        "--list-prefetch-pages",
        str(list_prefetch_pages),
        "--detail-batch-size",
        str(detail_batch_size),
    ]
    if full:
        start_page = prompt_int("Full sync start page (blank for resume)", 1, allow_blank=True)
        max_pages = prompt_int("Full sync max_pages (blank for all)", 1, allow_blank=True)
        if start_page is not None:
            args.extend(["--start-page", str(start_page)])
        if max_pages is not None:
            args.extend(["--max-pages", str(max_pages)])
    else:
        stable_pages = prompt_int("Latest sync stable_pages override", config.stable_pages)
        max_pages = prompt_int("Latest sync max_pages (blank for none)", 1, allow_blank=True)
        args.extend(["--stable-pages", str(stable_pages)])
        if max_pages is not None:
            args.extend(["--max-pages", str(max_pages)])
    return args


def run_manual_sync(config: DeployConfig, *, full: bool) -> None:
    if not confirm(f"Run {'sync full' if full else 'sync latest'} now?", default=True):
        return
    args = prompt_sync_command_args(config, full=full)
    cmd = [config.uv_bin, "run", "search-iwara", "sync", "full" if full else "latest", *args]
    print("\nRunning:")
    print("  " + " ".join(shlex.quote(part) for part in cmd))
    run_as_service_user(config, cmd)


def configure_existing(config: DeployConfig) -> DeployConfig:
    print("\nCurrent values will be shown as defaults.")
    return prompt_install_settings(config)


def manage_loop() -> None:
    require_root()
    if not sys.stdin.isatty():
        raise SystemExit("Interactive mode requires a TTY.")

    installed = is_installed()
    config = load_config() if installed else default_config()

    if not installed:
        print("Search Iwara is not installed on this system.")
        if not confirm("Install now?", default=True):
            return
        config = prompt_install_settings(config)
        print_config_summary(config)
        if not confirm("Apply this installation?", default=True):
            return
        install_or_update(config)
        print("\nInstallation complete.")
        show_status(load_config())
        return

    while True:
        config = load_config()
        print("\nSearch Iwara Linux Manager")
        print("  1) Show status")
        print("  2) Reconfigure deployment")
        print("  3) Update sync defaults only")
        print("  4) Run sync latest now")
        print("  5) Run sync full now")
        print("  6) Restart web service")
        print("  0) Exit")
        choice = input("Choose [1]: ").strip() or "1"

        if choice == "1":
            show_status(config)
        elif choice == "2":
            updated = configure_existing(config)
            print_config_summary(updated)
            if confirm("Apply deployment changes?", default=True):
                install_or_update(updated)
                print("Deployment updated.")
        elif choice == "3":
            updated = config
            prompt_sync_settings(updated)
            print_config_summary(updated)
            if confirm("Apply sync setting changes?", default=True):
                install_or_update(updated)
                print("Sync settings updated.")
        elif choice == "4":
            run_manual_sync(config, full=False)
        elif choice == "5":
            run_manual_sync(config, full=True)
        elif choice == "6":
            run(["systemctl", "restart", DEFAULT_WEB_UNIT])
            print("Web service restarted.")
        elif choice == "0":
            return
        else:
            print("Unknown choice.")


def main() -> None:
    manage_loop()


if __name__ == "__main__":
    main()
