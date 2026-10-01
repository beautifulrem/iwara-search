from __future__ import annotations

from pathlib import Path

from search_iwara_deploy import cli
from search_iwara_deploy import config as cfg
from search_iwara_deploy.config import Paths

from tests.deploy.conftest import make_config


def parse(*argv: str):  # type: ignore[no-untyped-def]
    return cli.build_parser().parse_args(list(argv))


def test_install_args_force_loopback_in_nginx_mode(paths: Paths):
    config = cli.config_from_install_args(
        parse("install", "--non-interactive", "--app-dir", "/opt/search-iwara", "--web-host", "0.0.0.0",
              "--sync-hours", "3"),
        paths,
    )  # fmt: skip
    assert config.deploy_mode == "nginx"
    assert config.web_host == "127.0.0.1"
    assert config.sync_hours == 3
    assert config.metrics_token == ""  # nginx denies remote /metrics; no token needed

    config = cli.config_from_install_args(
        parse("install", "--non-interactive", "--app-dir", "/opt/search-iwara", "--web-host", "0.0.0.0",
              "--skip-nginx"),
        paths,
    )  # fmt: skip
    assert config.deploy_mode == "public"
    assert config.web_host == "0.0.0.0"
    assert len(config.metrics_token) >= 32  # public bind -> /metrics protected by a bearer token
    assert cfg.validate_config(config) == []


def test_install_args_explicit_token_and_api_docs(paths: Paths):
    config = cli.config_from_install_args(
        parse("install", "--app-dir", "/opt/x", "--skip-nginx", "--web-host", "0.0.0.0",
              "--metrics-token", "my-own-token-1234567", "--api-docs"),
        paths,
    )  # fmt: skip
    assert config.metrics_token == "my-own-token-1234567"
    assert config.api_docs_enabled is True


def test_render_command_writes_all_files(tmp_path: Path, paths: Paths):
    cfg.write_env_file(paths.env_file, make_config())
    out = tmp_path / "out"
    cli.main(
        ["render", "--env-file", str(paths.env_file), "--systemd-dir", str(paths.systemd_dir),
         "--nginx-site", str(paths.nginx_site), "--output", str(out)]
    )  # fmt: skip
    names = {path.name for path in out.iterdir()}
    assert {"search-iwara.env", "search-iwara-web.service", "search-iwara.nginx.conf"} <= names


def test_menu_lists_every_action():
    assert list(cli.MENU) == [str(i) for i in range(1, 9)]


def test_manage_entry_point_runs_standalone(tmp_path: Path, paths: Paths):
    import subprocess
    import sys

    cfg.write_env_file(paths.env_file, make_config())
    script = Path(__file__).resolve().parents[2] / "deploy" / "linux" / "manage.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "render",
            "--env-file",
            str(paths.env_file),
            "--output",
            str(tmp_path / "o"),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd="/",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "o" / "search-iwara-web.service").exists()
