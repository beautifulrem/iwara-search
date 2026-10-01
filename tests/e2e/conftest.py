"""Shared E2E fixtures: a seeded app server per module and hermetic (offline) browsing."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest

pytest.importorskip("playwright")

import uvicorn
from playwright.sync_api import BrowserContext, Page, Route

from search_iwara.config import get_settings
from search_iwara.storage import CrawlStore
from search_iwara.web import create_app
from tests.factories import SAMPLE_MOVIES, make_detail, seed


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def app_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    db = tmp_path_factory.mktemp("e2e") / "e2e.sqlite3"
    store = CrawlStore.open(db)
    extra = tuple(
        make_detail(1000 + i, title=f"extra clip {i}", author=(11, "Author Eleven"), tags=[(31, "Tag Alpha")])
        for i in range(50)
    )
    seed(store, SAMPLE_MOVIES + extra)
    store.close()

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(get_settings(db_path=db)), port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def hermetic(target: BrowserContext | Page, app_url: str) -> None:
    """Serve only the app under test: every other request (e.g. the fixture thumbnails on
    oreno3d.com) gets an immediate 404, so results never depend on the network."""

    def route(request_route: Route) -> None:
        if request_route.request.url.startswith(app_url):
            request_route.continue_()
        else:
            request_route.fulfill(status=404, body="")

    target.route("**/*", route)


@pytest.fixture(autouse=True)
def _hermetic_page(request: pytest.FixtureRequest, app_url: str) -> None:
    if "page" in request.fixturenames:
        hermetic(request.getfixturevalue("page"), app_url)


def wait_ready(page: Page) -> None:
    """Wait for app.js to finish wiring the page (``html.js-ready``); plain load without JS."""

    if page.evaluate("() => document.documentElement.classList.contains('js')"):
        page.wait_for_selector("html.js-ready", state="attached")
    else:
        page.wait_for_load_state("load")
