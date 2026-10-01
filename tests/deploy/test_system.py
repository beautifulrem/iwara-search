from __future__ import annotations

import subprocess

import pytest
from search_iwara_deploy import shell, system

from tests.deploy.conftest import make_config


def test_service_commands_drop_supplementary_groups():
    kwargs = system.service_user_kwargs(make_config())
    assert kwargs == {"user": "searchiwara", "group": "searchiwara", "extra_groups": []}


def test_service_env_only_exports_runtime_values():
    env = system.service_env(make_config(proxy="", metrics_token="x" * 32), interactive=True)
    assert env["SEARCH_IWARA_DB"] == "/var/lib/search-iwara/oreno3d.sqlite3"
    assert env["SEARCH_IWARA_REQUEST_RATE"] == "1.5"
    assert env["SEARCH_IWARA_LOG_FORMAT"] == "text"
    assert "SEARCH_IWARA_PROXY" not in env
    assert "SEARCH_IWARA_ALERT_WEBHOOK" not in env
    assert "SEARCH_IWARA_METRICS_TOKEN" not in env
    assert env["HOME"] == "/var/lib/search-iwara"


def test_run_service_command_uses_argv_and_drops_privileges(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 75, "", "")

    monkeypatch.setattr(shell, "run", fake_run)
    code = system.run_service_command(make_config(), ["sync", "latest"])
    assert code == 75
    cmd, kwargs = calls[0]
    assert cmd == ["/opt/search-iwara/.venv/bin/search-iwara", "sync", "latest"]
    assert kwargs["user"] == "searchiwara"
    assert kwargs["extra_groups"] == []
    assert kwargs["check"] is False


def test_metrics_access_summary():
    assert "bearer" in system.metrics_access_summary(make_config(metrics_token="t" * 32))
    assert "disabled" in system.metrics_access_summary(make_config(deploy_mode="public", web_host="0.0.0.0"))
    assert "nginx" in system.metrics_access_summary(make_config())
    labels = dict(system.config_summary_rows(make_config(api_docs_enabled=True)))
    assert labels["api docs"] == "enabled"
    assert "hsts max-age" in labels


def test_sync_exit_messages_cover_documented_codes():
    assert set(system.SYNC_EXIT_MESSAGES) == {0, 1, 2, 75}


def test_systemctl_value_is_empty_when_unavailable(monkeypatch: pytest.MonkeyPatch):
    def missing(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("systemctl")

    monkeypatch.setattr(subprocess, "run", missing)
    assert shell.systemctl_value("x.service", "User") == ""
    assert shell.systemctl_state("x.service") == ("unknown", "unknown")


def _debian_layout(tmp_path):  # type: ignore[no-untyped-def]
    from search_iwara_deploy.config import Paths

    available, enabled = tmp_path / "sites-available", tmp_path / "sites-enabled"
    available.mkdir()
    enabled.mkdir()
    (available / "default").write_text("server { listen 80 default_server; }")
    (enabled / "default").symlink_to(available / "default")
    paths = Paths(
        env_file=tmp_path / "env",
        systemd_dir=tmp_path / "systemd",
        nginx_site=available / "search-iwara.conf",
        nginx_enabled=enabled / "search-iwara.conf",
    )
    return paths, enabled / "default"


def test_catch_all_install_disables_the_stock_default_site(tmp_path):  # type: ignore[no-untyped-def]
    paths, default_link = _debian_layout(tmp_path)
    result = system.disable_stock_default_site(make_config(server_name="_"), paths)
    assert result is not None
    assert not default_link.exists()
    assert (tmp_path / "sites-available" / "default").exists()  # file kept for re-enabling


def test_named_site_or_custom_default_is_left_alone(tmp_path):  # type: ignore[no-untyped-def]
    paths, default_link = _debian_layout(tmp_path)
    assert system.disable_stock_default_site(make_config(server_name="search.example.com"), paths) is None
    assert default_link.is_symlink()
    default_link.unlink()
    custom = tmp_path / "elsewhere" / "default"
    custom.parent.mkdir()
    custom.write_text("server {}")
    default_link.symlink_to(custom)
    assert system.disable_stock_default_site(make_config(server_name="_"), paths) is None
    assert default_link.is_symlink()
