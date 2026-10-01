from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "deploy" / "linux"
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

from search_iwara_deploy.config import DeployConfig, Paths  # noqa: E402


def make_config(**overrides: object) -> DeployConfig:
    config = DeployConfig(
        app_dir="/opt/search-iwara",
        uv_bin="/usr/local/bin/uv",
        db_path="/var/lib/search-iwara/oreno3d.sqlite3",
        backup_dir="/var/backups/search-iwara",
        web_host="127.0.0.1",
        web_port=9000,
        deploy_mode="nginx",
        service_user="searchiwara",
        service_group="searchiwara",
        sync_hours=4,
        stable_pages=2,
        max_pages="5",
        request_concurrency=3,
        request_rate=1.5,
        list_prefetch_pages=2,
        proxy="socks5://127.0.0.1:1080",
        trust_env=False,
        log_format="json",
        log_level="INFO",
        backup_keep=14,
        alert_webhook="https://ntfy.sh/topic?token=a b",
        server_name="search.example.com",
        tls_mode="https",
        tls_cert_file="/etc/ssl/certs/search.pem",
        tls_key_file="/etc/ssl/private/search.key",
        hsts_max_age=31536000,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(
        env_file=tmp_path / "search-iwara.env",
        systemd_dir=tmp_path / "systemd",
        nginx_site=tmp_path / "nginx" / "search-iwara.conf",
        nginx_enabled=None,
    )
