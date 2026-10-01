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
