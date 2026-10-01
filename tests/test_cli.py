from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

import pytest
from typer.testing import CliRunner

from search_iwara import __version__, cli
from search_iwara.crawler import RetriesExhaustedError
from search_iwara.models import ListingPage
from search_iwara.parsers import ParserDriftError
from search_iwara.services import sync_lock
from search_iwara.storage import SCHEMA_VERSION
from tests.test_services import FakeClient

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SEARCH_IWARA_DB", "SEARCH_IWARA_PROXY", "SEARCH_IWARA_REQUEST_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)


def install_client(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    class Wrapper:
        def __init__(self, settings: object) -> None:
            self.client = client

        async def __aenter__(self) -> FakeClient:
            return self.client

        async def __aexit__(
            self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
        ) -> None:
            return None

    monkeypatch.setattr(cli, "Oreno3dClient", Wrapper)


def invoke(*args: str) -> tuple[int, str]:
    result = runner.invoke(cli.app, list(args))
    return result.exit_code, result.output


def test_version() -> None:
    code, output = invoke("--version")
    assert code == 0
    assert __version__ in output


def test_db_migrate_and_refresh(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    code, output = invoke("db", "migrate", "--db-path", str(db))
    assert code == 0
    assert f"schema v{SCHEMA_VERSION}" in output
    code, output = invoke("db", "migrate", "--db-path", str(db))
    assert "0 migration(s)" in output
    code, _ = invoke("db", "refresh", "--db-path", str(db))
    assert code == 0


def test_db_backup_rotates(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    invoke("db", "migrate", "--db-path", str(db))
    backups = tmp_path / "backups"
    backups.mkdir()
    for stamp in ("20200101T000000Z", "20200102T000000Z"):
        (backups / f"db-{stamp}.sqlite3").write_bytes(b"old")
    code, output = invoke("db", "backup", "--db-path", str(db), "--dest", str(backups), "--keep", "2")
    assert code == 0, output
    remaining = sorted(path.name for path in backups.iterdir())
    assert remaining[0] == "db-20200102T000000Z.sqlite3"
    assert len(remaining) == 2
    copy = sqlite3.connect(backups / remaining[1])
    assert copy.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    copy.close()


def test_db_backup_without_database(tmp_path: Path) -> None:
    code, output = invoke("db", "backup", "--db-path", str(tmp_path / "missing.sqlite3"))
    assert code == 1
    assert "no database" in output


def test_sync_latest_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_client(monkeypatch, FakeClient([3, 2, 1]))
    code, output = invoke("sync", "latest", "--db-path", str(tmp_path / "db.sqlite3"), "--stable-pages", "1")
    assert code == 0, output
    assert "new=3" in output


def test_sync_full_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_client(monkeypatch, FakeClient([6, 5, 4, 3, 2, 1]))
    code, output = invoke("sync", "full", "--db-path", str(tmp_path / "db.sqlite3"), "--max-pages", "1")
    assert code == 0, output
    assert "pages=1" in output


def test_sync_exit_code_on_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_client(monkeypatch, FakeClient([3, 2, 1], failing_pages={1}))
    code, _ = invoke("sync", "latest", "--db-path", str(tmp_path / "db.sqlite3"), "--max-pages", "1")
    assert code == cli.EXIT_FAILURES


def test_sync_detail_failures_within_tolerance_succeed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_client(
        monkeypatch, FakeClient([3, 2, 1], failing_details={2: RetriesExhaustedError("u", 1, "x")})
    )
    code, _ = invoke("sync", "latest", "--db-path", str(tmp_path / "db.sqlite3"), "--stable-pages", "1")
    assert code == 0


def test_sync_exit_code_on_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Drifted(FakeClient):
        async def fetch_listing_page(self, page: int) -> ListingPage:
            raise ParserDriftError("grid missing")

    install_client(monkeypatch, Drifted([]))
    code, _ = invoke("sync", "latest", "--db-path", str(tmp_path / "db.sqlite3"))
    assert code == cli.EXIT_DRIFT


def test_sync_exit_code_when_locked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "db.sqlite3"
    install_client(monkeypatch, FakeClient([1]))
    with sync_lock(db):
        code, _ = invoke("sync", "latest", "--db-path", str(db))
    assert code == cli.EXIT_LOCKED


def test_invalid_configuration_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_IWARA_REQUEST_CONCURRENCY", "0")
    code, output = invoke("db", "migrate", "--db-path", str(tmp_path / "db.sqlite3"))
    assert code == cli.EXIT_CONFIG
    assert "request_concurrency" in output


def test_serve_passes_hardened_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    captured: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    code, output = invoke("serve", "--db-path", str(tmp_path / "db.sqlite3"), "--port", "8123")
    assert code == 0, output
    assert captured["port"] == 8123
    assert captured["server_header"] is False
    assert captured["proxy_headers"] is True
    assert captured["forwarded_allow_ips"] == "127.0.0.1"

    captured.clear()
    code, _ = invoke("serve", "--db-path", str(tmp_path / "db.sqlite3"), "--reload")
    assert code == 0
    assert captured["app"] == "search_iwara.web:create_app"
    assert captured["factory"] is True


def test_sync_exit_code_when_robots_unreachable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from search_iwara.crawler import RobotsUnavailableError

    class NoRobots(FakeClient):
        async def fetch_listing_page(self, page: int) -> ListingPage:
            raise RobotsUnavailableError("https://oreno3d.com/robots.txt is unreachable")

    install_client(monkeypatch, NoRobots([]))
    code, _ = invoke("sync", "latest", "--db-path", str(tmp_path / "db.sqlite3"))
    assert code == cli.EXIT_FAILURES


def test_sync_exit_code_when_terminated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    class Terminated(FakeClient):
        async def fetch_listing_page(self, page: int) -> ListingPage:
            raise asyncio.CancelledError  # what SIGTERM's handler triggers on the main task

    install_client(monkeypatch, Terminated([]))
    code, _ = invoke("sync", "latest", "--db-path", str(tmp_path / "db.sqlite3"))
    assert code == cli.EXIT_TERMINATED
