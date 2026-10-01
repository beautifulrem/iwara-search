from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from search_iwara.config import Settings, get_settings
from search_iwara.storage import CrawlStore
from search_iwara.web import create_app
from tests.factories import seed


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite3"


@pytest.fixture
def settings(db_path: Path) -> Settings:
    return get_settings(db_path=db_path, log_format="text")


@pytest.fixture
def store(db_path: Path) -> Iterator[CrawlStore]:
    crawl_store = CrawlStore.open(db_path)
    yield crawl_store
    crawl_store.close()


@pytest.fixture
def seeded(store: CrawlStore) -> CrawlStore:
    seed(store)
    return store


@pytest.fixture
def client(seeded: CrawlStore, settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
