from __future__ import annotations

import re

import pytest
from search_iwara_deploy import render
from search_iwara_deploy.config import Paths

from tests.deploy.conftest import make_config

HARDENING_DIRECTIVES = (
    "NoNewPrivileges=true",
    "PrivateTmp=true",
    "PrivateDevices=true",
    "ProtectSystem=strict",
    "ProtectKernelTunables=true",
    "ProtectKernelModules=true",
    "ProtectKernelLogs=true",
    "ProtectControlGroups=true",
    "ProtectClock=true",
    "ProtectHostname=true",
    "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
    "RestrictNamespaces=true",
    "RestrictRealtime=true",
    "LockPersonality=true",
    "MemoryDenyWriteExecute=true",
    "SystemCallArchitectures=native",
    "SystemCallFilter=@system-service",
    "CapabilityBoundingSet=\n",
    "UMask=0027",
)


def test_units_are_hardened_and_do_not_use_uv_run(paths: Paths):
    units = render.render_units(make_config(), paths)
    assert set(units) == set(render.UNIT_TEMPLATES)
    for name in (
        "search-iwara-web.service",
        "search-iwara-sync.service",
        "search-iwara-backup.service",
        "search-iwara-alert@.service",
    ):
        text = units[name]
        for directive in HARDENING_DIRECTIVES:
            assert directive in text, f"{name} is missing {directive!r}"
        assert "ProtectHome=true" in text
        assert "ReadWritePaths=/var/lib/search-iwara -/var/backups/search-iwara" in text
        assert "User=searchiwara" in text
        assert "uv run" not in text
        assert not re.search(r"__[A-Z_]+__", text)
    for name in ("search-iwara-web.service", "search-iwara-sync.service", "search-iwara-backup.service"):
        assert "OnFailure=search-iwara-alert@%n.service" in units[name]


def test_web_unit_migrates_before_start(paths: Paths):
    web = render.render_units(make_config(), paths)["search-iwara-web.service"]
    assert "ExecStartPre=/opt/search-iwara/.venv/bin/search-iwara db migrate" in web
    assert f"EnvironmentFile={paths.env_file}" in web
    assert "Restart=on-failure" in web


def test_sync_unit_treats_lock_contention_as_success(paths: Paths):
    units = render.render_units(make_config(), paths)
    sync = units["search-iwara-sync.service"]
    assert "SuccessExitStatus=75" in sync
    assert "\n[Install]\n" not in sync  # only the timer is enabled

    timer = units["search-iwara-sync.timer"]
    assert "OnCalendar=*-*-* 0/4:00:00" in timer
    assert "RandomizedDelaySec=10min" in timer
    assert "Persistent=true" in timer
    assert "OnUnitActiveSec" not in timer

    backup_timer = units["search-iwara-backup.timer"]
    assert "OnCalendar=" in backup_timer
    assert "Persistent=true" in backup_timer


def test_sync_on_calendar_bounds():
    assert render.sync_on_calendar(1) == "*-*-* 0/1:00:00"
    assert render.sync_on_calendar(24) == "*-*-* 00:00:00"
    with pytest.raises(ValueError):
        render.sync_on_calendar(25)


def test_checkout_under_home_uses_read_only_protect_home(paths: Paths):
    config = make_config(
        app_dir="/home/alice/search-iwara",
        db_path="/home/alice/search-iwara/data/db.sqlite3",
        backup_dir="/home/alice/search-iwara/data/backups",
    )
    web = render.render_units(config, paths)["search-iwara-web.service"]
    assert "ProtectHome=read-only" in web
    # backup dir lives inside the data dir, so it is not listed twice
    assert "ReadWritePaths=/home/alice/search-iwara/data\n" in web


def test_render_template_rejects_leftover_placeholders(tmp_path):
    template = tmp_path / "x.template"
    template.write_text("a=__KNOWN__ b=__MISSING__", encoding="utf-8")
    with pytest.raises(ValueError, match="__MISSING__"):
        render.render_template(template, {"__KNOWN__": "1"})


def test_render_nginx_http_config():
    config = make_config(tls_mode="http", tls_cert_file="", tls_key_file="")
    text = render.render_nginx_config(config, (1, 24, 0))
    assert "server_name search.example.com;" in text
    assert "proxy_pass http://127.0.0.1:9000;" in text
    assert "ssl_certificate" not in text
    assert "Strict-Transport-Security" not in text
    assert "gzip on;" in text
    assert "image/svg+xml" in text
    assert "server_tokens off;" in text
    assert "client_max_body_size 16k;" in text
    assert "alias /opt/search-iwara/search_iwara/static/;" in text
    assert 'add_header Cache-Control "public, immutable" always;' in text
    assert "expires 1y;" in text
    assert "limit_req_zone $binary_remote_addr zone=search_iwara_pages:10m rate=10r/s;" in text
    assert "limit_req zone=search_iwara_api burst=40 nodelay;" in text
    assert not re.search(r"__[A-Z_]+__", text)


def test_nginx_metrics_is_loopback_only():
    text = render.render_nginx_config(make_config(), None)
    block = text.split("location = /metrics {", 1)[1].split("}", 1)[0]
    assert "allow 127.0.0.1;" in block
    assert "deny all;" in block


def test_render_nginx_https_modern_nginx():
    text = render.render_nginx_config(make_config(), (1, 26, 2))
    assert "return 301 https://$host$request_uri;" in text
    assert "listen 443 ssl;" in text
    assert "http2 on;" in text
    assert "listen 443 ssl http2;" not in text
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in text
    assert "ssl_prefer_server_ciphers off;" in text
    assert "ssl_session_cache shared:search_iwara_tls:10m;" in text
    assert "ssl_certificate /etc/ssl/certs/search.pem;" in text
    assert "ssl_certificate_key /etc/ssl/private/search.key;" in text
    # HSTS on the server and repeated in /static/ (add_header is not inherited there)
    assert text.count('Strict-Transport-Security "max-age=31536000; includeSubDomains" always;') == 2


def test_render_nginx_https_legacy_nginx_uses_listen_http2():
    text = render.render_nginx_config(make_config(), (1, 22, 1))
    assert "listen 443 ssl http2;" in text
    assert "http2 on;" not in text


def test_hsts_can_be_disabled():
    assert "Strict-Transport-Security" not in render.render_nginx_config(make_config(hsts_max_age=0), None)


def test_parse_nginx_version_and_upstream_host():
    assert render.parse_nginx_version("nginx version: nginx/1.25.1\n") == (1, 25, 1)
    assert render.parse_nginx_version("garbage") is None
    assert render.parse_nginx_version(None) is None
    assert render.upstream_host("0.0.0.0") == "127.0.0.1"
    assert render.upstream_host("::") == "[::1]"
    assert render.upstream_host("fd00::1") == "[fd00::1]"
    assert render.upstream_host("10.0.0.2") == "10.0.0.2"


def test_catch_all_site_is_the_default_server():
    text = render.render_nginx_config(make_config(server_name="_", tls_mode="http"), (1, 22, 1))
    assert "listen 80 default_server;" in text
    assert "listen [::]:80 default_server;" in text
    named = render.render_nginx_config(make_config(tls_mode="http"), (1, 22, 1))
    assert "default_server" not in named
