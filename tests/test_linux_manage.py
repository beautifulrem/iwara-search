from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy" / "linux" / "manage.py"
SPEC = importlib.util.spec_from_file_location("linux_manage", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
linux_manage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = linux_manage
SPEC.loader.exec_module(linux_manage)


def test_env_roundtrip(tmp_path: Path):
    env_file = tmp_path / "search-iwara.env"
    config = linux_manage.DeployConfig(
        app_dir="/srv/search-iwara",
        uv_bin="/usr/local/bin/uv",
        db_path="/srv/search-iwara/data/oreno3d.sqlite3",
        web_host="127.0.0.1",
        web_port=9000,
        stable_pages=2,
        max_pages="5",
        request_concurrency=24,
        request_delay_ms=0,
        list_prefetch_pages=16,
        detail_batch_size=192,
        sync_hours=4,
        deploy_mode="nginx",
        service_user="searchiwara",
        service_group="searchiwara",
        server_name="search.example.com",
        tls_mode="https",
        tls_cert_file="/etc/ssl/certs/search.pem",
        tls_key_file="/etc/ssl/private/search.key",
    )

    linux_manage.write_env_file(env_file, config)
    loaded = linux_manage.load_config(env_file)

    assert loaded == config


def test_render_nginx_http_config():
    config = linux_manage.default_config()
    config.deploy_mode = "nginx"
    config.server_name = "search.example.com"
    config.tls_mode = "http"
    text = linux_manage.render_nginx_config(config)

    assert "server_name search.example.com;" in text
    assert "proxy_pass http://127.0.0.1:8000;" in text
    assert "ssl_certificate" not in text


def test_render_nginx_https_config():
    config = linux_manage.default_config()
    config.deploy_mode = "nginx"
    config.server_name = "search.example.com"
    config.tls_mode = "https"
    config.tls_cert_file = "/etc/ssl/certs/search.pem"
    config.tls_key_file = "/etc/ssl/private/search.key"
    text = linux_manage.render_nginx_config(config)

    assert "return 301 https://$host$request_uri;" in text
    assert "listen 443 ssl http2;" in text
    assert "ssl_certificate /etc/ssl/certs/search.pem;" in text
    assert "ssl_certificate_key /etc/ssl/private/search.key;" in text
