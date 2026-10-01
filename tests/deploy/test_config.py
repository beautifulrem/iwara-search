from __future__ import annotations

import pytest
from search_iwara_deploy import config as cfg
from search_iwara_deploy.config import Paths

from tests.deploy.conftest import make_config


def test_env_roundtrip_preserves_every_field(paths: Paths):
    config = make_config(metrics_token="abcdefghijklmnopqrstuvwxyz_-0123", api_docs_enabled=True)
    cfg.write_env_file(paths.env_file, config)
    loaded, notes = cfg.load_config(paths)
    assert loaded == config
    assert notes == []
    assert paths.env_file.stat().st_mode & 0o777 == 0o600


def test_env_file_comments_out_empty_values_and_quotes_special_ones(paths: Paths):
    config = make_config(proxy="", max_pages="")
    text = cfg.render_env_file(config)
    assert "# SEARCH_IWARA_PROXY=\n" in text
    assert "# SEARCH_IWARA_MAX_PAGES=\n" in text
    assert "# SEARCH_IWARA_METRICS_TOKEN=\n" in text
    assert "SEARCH_IWARA_API_DOCS_ENABLED=false" in text
    assert 'SEARCH_IWARA_ALERT_WEBHOOK="https://ntfy.sh/topic?token=a b"' in text
    assert "SEARCH_IWARA_TRUST_ENV=false" in text
    assert "REQUEST_DELAY_MS" not in text
    assert "DETAIL_BATCH_SIZE" not in text
    cfg.write_env_file(paths.env_file, config)
    assert cfg.load_config(paths)[0] == config


def test_legacy_env_is_migrated(paths: Paths):
    paths.env_file.write_text(
        "\n".join(
            [
                "APP_DIR=/srv/search-iwara",
                "UV_BIN=/usr/local/bin/uv",
                "SEARCH_IWARA_DB=/srv/search-iwara/data/oreno3d.sqlite3",
                "SEARCH_IWARA_HOST=127.0.0.1",
                "SEARCH_IWARA_PORT=8000",
                "SEARCH_IWARA_STABLE_PAGES=3",
                "SEARCH_IWARA_MAX_PAGES=",
                "SEARCH_IWARA_REQUEST_CONCURRENCY=12",
                "SEARCH_IWARA_REQUEST_DELAY_MS=1000",
                "SEARCH_IWARA_LIST_PREFETCH_PAGES=8",
                "SEARCH_IWARA_DETAIL_BATCH_SIZE=96",
                "SEARCH_IWARA_SYNC_HOURS=6",
                "SEARCH_IWARA_DEPLOY_MODE=local",
                "SEARCH_IWARA_SERVICE_USER=alice",
                "SEARCH_IWARA_SERVICE_GROUP=alice",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config, notes = cfg.load_config(paths)
    assert config.request_rate == 1.0  # 1000 ms delay -> 1 req/s (slower than the 2/s default)
    assert config.request_concurrency == 4  # old aggressive default lowered
    assert config.list_prefetch_pages == 4
    assert config.service_user == "alice"  # existing account is kept, not silently changed
    assert config.backup_dir == "/srv/search-iwara/data/backups"
    assert config.log_format == "json"
    assert config.api_docs_enabled is False
    assert any("REQUEST_DELAY_MS" in note for note in notes)
    assert any("DETAIL_BATCH_SIZE" in note for note in notes)

    cfg.write_env_file(paths.env_file, config)
    rewritten = paths.env_file.read_text(encoding="utf-8")
    assert "REQUEST_DELAY_MS" not in rewritten
    assert "SEARCH_IWARA_REQUEST_RATE=1.0" in rewritten


def test_legacy_zero_delay_uses_polite_default_rate():
    values, _ = cfg.migrate_legacy_env(
        {"SEARCH_IWARA_REQUEST_DELAY_MS": "0", "SEARCH_IWARA_REQUEST_CONCURRENCY": "24"}
    )
    assert values["SEARCH_IWARA_REQUEST_RATE"] == "2.0"
    assert values["SEARCH_IWARA_REQUEST_CONCURRENCY"] == "24"  # explicit user choice kept


def test_env_value_parsing():
    assert cfg.parse_env_value('"a \\"b\\" c"') == 'a "b" c'
    assert cfg.parse_env_value("'x y'") == "x y"
    assert cfg.format_env_value("plain/value:1") == "plain/value:1"
    assert cfg.format_env_value('needs "quotes"') == '"needs \\"quotes\\""'


def test_default_config_is_polite_and_uses_dedicated_account():
    config = cfg.default_config("/opt/search-iwara")
    assert config.service_user == config.service_group == "searchiwara"
    assert config.request_concurrency == 4
    assert config.request_rate == 2.0
    assert config.backup_dir == "/opt/search-iwara/data/backups"
    assert config.api_docs_enabled is False
    assert cfg.validate_config(config) == []


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"sync_hours": 0}, "sync_hours"),
        ({"sync_hours": 48}, "sync_hours"),
        ({"request_rate": 0}, "request_rate"),
        ({"deploy_mode": "nginx", "tls_mode": "https", "tls_cert_file": ""}, "tls_cert_file"),
        ({"service_user": "bad user"}, "invalid account"),
        ({"db_path": "relative/db.sqlite3"}, "absolute"),
        ({"app_dir": "/opt/with space"}, "whitespace"),
        ({"log_format": "xml"}, "log_format"),
        ({"max_pages": "²"}, "max_pages"),
        ({"metrics_token": "short"}, "metrics_token"),
        ({"metrics_token": "has spaces in the token value"}, "metrics_token"),
    ],
)
def test_validate_config_rejects_bad_values(overrides, fragment):
    errors = cfg.validate_config(make_config(**overrides))
    assert any(fragment in error for error in errors), errors


def test_metrics_token_is_generated_only_for_public_binds():
    public = make_config(deploy_mode="public", web_host="0.0.0.0", metrics_token="")
    assert public.metrics_exposed_publicly
    assert cfg.ensure_metrics_token(public)
    assert len(public.metrics_token) >= 32
    assert cfg.validate_config(public) == []
    assert not cfg.ensure_metrics_token(public)  # an existing token is kept

    for mode, host in (("nginx", "127.0.0.1"), ("local", "127.0.0.1")):
        private = make_config(deploy_mode=mode, web_host=host, metrics_token="")
        assert not cfg.ensure_metrics_token(private)
        assert private.metrics_token == ""
