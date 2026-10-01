"""Command line: ``install``/``update``/``backup``/``status``/``render`` and the interactive menu."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

from . import prompts, system
from .config import (
    LOOPBACK_HOSTS,
    PUBLIC_HOST,
    DeployConfig,
    Paths,
    default_config,
    default_paths,
    ensure_metrics_token,
    is_installed,
    load_config,
    render_env_file,
    validate_config,
)
from .render import parse_nginx_version, render_nginx_config, render_units
from .shell import nginx_version_output

INSTALL_OVERRIDES: Final = (
    "app_dir",
    "db_path",
    "service_user",
    "service_group",
    "web_host",
    "web_port",
    "sync_hours",
    "server_name",
    "tls_cert_file",
    "tls_key_file",
    "hsts_max_age",
    "uv_bin",
    "metrics_token",
)


# --- argument parsing -----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search Iwara Linux deployment manager")
    sub = parser.add_subparsers(dest="command")

    install = sub.add_parser("install", help="install or reconfigure the deployment")
    install.add_argument("--non-interactive", action="store_true")
    install.add_argument("--app-dir")
    install.add_argument("--db-path")
    install.add_argument("--backup-dir")
    install.add_argument("--user", dest="service_user")
    install.add_argument("--group", dest="service_group")
    install.add_argument("--web-host")
    install.add_argument("--web-port", type=int)
    install.add_argument("--sync-hours", type=int)
    install.add_argument("--server-name")
    install.add_argument("--tls-cert", dest="tls_cert_file")
    install.add_argument("--tls-key", dest="tls_key_file")
    install.add_argument("--hsts-max-age", type=int)
    install.add_argument("--uv-bin")
    install.add_argument("--metrics-token", help="bearer token for /metrics (generated in public mode)")
    install.add_argument("--api-docs", action=argparse.BooleanOptionalAction, default=None)
    nginx = install.add_mutually_exclusive_group()
    nginx.add_argument("--skip-nginx", action="store_true", help="no nginx; bind the app directly")
    nginx.add_argument("--nginx", action="store_true", help="force nginx reverse-proxy mode")

    for name in ("install", "update", "backup", "status", "render"):
        target = install if name == "install" else sub.add_parser(name, help=f"{name} the deployment")
        target.add_argument("--env-file", type=Path)
        target.add_argument("--systemd-dir", type=Path)
        target.add_argument("--nginx-site", type=Path, help="path of the rendered nginx site file")
        target.add_argument("--nginx-enabled", type=Path, help="sites-enabled symlink path (Debian layout)")
        if name == "render":
            target.add_argument("--output", type=Path, required=True, help="directory for the rendered files")
    return parser


def resolve_paths(args: argparse.Namespace) -> Paths:
    paths = default_paths()
    if getattr(args, "env_file", None):
        paths.env_file = args.env_file
    if getattr(args, "systemd_dir", None):
        paths.systemd_dir = args.systemd_dir
    if getattr(args, "nginx_site", None):
        paths.nginx_site = args.nginx_site
        paths.nginx_enabled = None
    if getattr(args, "nginx_enabled", None):
        paths.nginx_enabled = args.nginx_enabled
    return paths


def config_from_install_args(args: argparse.Namespace, paths: Paths) -> DeployConfig:
    installed = is_installed(paths)
    config = load_config(paths)[0] if installed else default_config(args.app_dir)
    for attr in INSTALL_OVERRIDES:
        value = getattr(args, attr, None)
        if value is not None:
            setattr(config, attr, value)
    if args.api_docs is not None:
        config.api_docs_enabled = args.api_docs
    if args.db_path and not args.backup_dir and not installed:
        config.backup_dir = str(Path(config.db_path).parent / "backups")
    if args.backup_dir:
        config.backup_dir = args.backup_dir
    if args.skip_nginx:
        config.deploy_mode = "public" if config.web_host == PUBLIC_HOST else "local"
    elif args.nginx or not installed:
        config.deploy_mode = "nginx"
    if config.deploy_mode == "nginx":
        if config.web_host not in LOOPBACK_HOSTS:
            print(f"note: nginx mode binds the app to 127.0.0.1 (was {config.web_host})")
        config.web_host = "127.0.0.1"
        config.tls_mode = "https" if config.tls_cert_file and config.tls_key_file else "http"
    if ensure_metrics_token(config):
        print("note: generated a /metrics bearer token (SEARCH_IWARA_METRICS_TOKEN) for the public bind.")
    return config


def render_to_directory(config: DeployConfig, paths: Paths, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "search-iwara.env").write_text(render_env_file(config), encoding="utf-8")
    for unit, text in render_units(config, paths).items():
        (output / unit).write_text(text, encoding="utf-8")
    nginx = render_nginx_config(config, parse_nginx_version(nginx_version_output()))
    (output / "search-iwara.nginx.conf").write_text(nginx, encoding="utf-8")
    print(f"Rendered deployment files into {output}")


# --- interactive ----------------------------------------------------------------------------


def run_manual_sync(config: DeployConfig, *, full: bool) -> int:
    mode = "full" if full else "latest"
    if not prompts.confirm(f"Run sync {mode} now?"):
        return 0
    args = ["sync", mode, *prompts.prompt_sync_command_args(config, full=full)]
    code = system.run_service_command(config, args, interactive=True)
    print(system.SYNC_EXIT_MESSAGES.get(code, f"sync exited with unexpected code {code}"))
    return code


def interactive_install(config: DeployConfig, paths: Paths) -> None:
    config = prompts.prompt_install_settings(config)
    system.print_config_summary(config)
    errors = validate_config(config)
    if errors:
        print("Invalid configuration:\n  - " + "\n  - ".join(errors))
        return
    if prompts.confirm("Apply this installation?"):
        system.apply_install(config, paths)
        print("\nInstallation complete.")
        system.show_status(load_config(paths)[0], paths)


def update_settings(config: DeployConfig, paths: Paths) -> None:
    prompts.prompt_sync_settings(config)
    prompts.prompt_ops_settings(config)
    system.print_config_summary(config)
    if prompts.confirm("Apply changes?"):
        system.apply_install(config, paths)


def redeploy(config: DeployConfig, paths: Paths) -> None:
    if prompts.confirm("Pull the latest code and redeploy?"):
        system.update_deployment(config, paths)


def restart(config: DeployConfig, paths: Paths) -> None:
    system.restart_web()
    print("Web service restarted.")


Action = Callable[[DeployConfig, Paths], object]
MENU: Final[dict[str, tuple[str, Action]]] = {
    "1": ("Show status", system.show_status),
    "2": ("Reconfigure deployment", interactive_install),
    "3": ("Update sync / ops settings", update_settings),
    "4": ("Run sync latest now", lambda config, _: run_manual_sync(config, full=False)),
    "5": ("Run sync full now", lambda config, _: run_manual_sync(config, full=True)),
    "6": ("Back up the database now", lambda config, _: system.backup_now(config)),
    "7": ("Update (git pull, uv sync, migrate, restart)", redeploy),
    "8": ("Restart web service", restart),
}


def manage_loop(paths: Paths) -> None:
    if not sys.stdin.isatty():
        raise system.DeployError(
            "Interactive mode requires a TTY. Use `manage.py install --non-interactive ...` for automation."
        )
    if not is_installed(paths):
        print("Search Iwara is not installed on this system.")
        if prompts.confirm("Install now?"):
            interactive_install(default_config(), paths)
        return

    _, notes = load_config(paths)
    for note in notes:
        print(f"migrated legacy setting: {note}")
    if notes:
        print("Choose 3) and apply to persist the migrated settings.")

    while True:
        config, _ = load_config(paths)
        print("\nSearch Iwara Linux Manager")
        for key, (label, _) in MENU.items():
            print(f"  {key}) {label}")
        print("  0) Exit")
        choice = input("Choose [1]: ").strip() or "1"
        if choice == "0":
            return
        entry = MENU.get(choice)
        if entry is None:
            print("Unknown choice.")
            continue
        entry[1](config, paths)


# --- entry point ----------------------------------------------------------------------------


def require_root() -> None:
    if os.geteuid() != 0:
        raise system.DeployError("Run this script with sudo or as root.")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    paths = resolve_paths(args)

    if args.command == "render":
        render_to_directory(load_config(paths)[0], paths, args.output)
        return

    require_root()
    if args.command is None:
        manage_loop(paths)
    elif args.command == "install":
        config = config_from_install_args(args, paths)
        if args.non_interactive:
            system.apply_install(config, paths)
            system.print_config_summary(config)
        else:
            interactive_install(config, paths)
    elif args.command == "update":
        system.update_deployment(load_config(paths)[0], paths)
    elif args.command == "backup":
        raise SystemExit(system.backup_now(load_config(paths)[0]))
    elif args.command == "status":
        system.show_status(load_config(paths)[0], paths)
