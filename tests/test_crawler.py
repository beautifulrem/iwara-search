from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from search_iwara.config import Settings, get_settings
from search_iwara.crawler import (
    AdaptiveRateLimiter,
    CrawlerConfigError,
    Oreno3dClient,
    RemoteClientError,
    RemoteNotFoundError,
    RemoteUnavailableError,
    RetriesExhaustedError,
    RobotsDisallowedError,
    RobotsUnavailableError,
    backoff_delay,
    parse_retry_after,
)
from tests.test_parsers import DETAIL_HTML, DETAIL_HTML_PLACEHOLDER, LISTING_HTML

Handler = Callable[[httpx.Request], httpx.Response]


def make_settings(tmp_path, **overrides) -> Settings:  # type: ignore[no-untyped-def]
    values = {"request_rate": 50.0, "request_retries": 3, "http2": False, "trust_env": False}
    values.update(overrides)
    return get_settings(db_path=tmp_path / "c.sqlite3", **values)


class Recorder:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def run(settings: Settings, handler: Handler, action, sleep: Recorder | None = None):  # type: ignore[no-untyped-def]
    async def main():  # type: ignore[no-untyped-def]
        async with Oreno3dClient(
            settings, transport=httpx.MockTransport(handler), rng=random.Random(0), sleep=sleep or Recorder()
        ) as client:
            return await action(client)

    return asyncio.run(main())


def site(routes: dict[str, list[httpx.Response] | httpx.Response], robots: str = "") -> Handler:
    calls: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path + (f"?{request.url.query.decode()}" if request.url.query else "")
        if path == "/robots.txt":
            return httpx.Response(200, text=robots) if robots else httpx.Response(404)
        for prefix, responses in routes.items():
            if path.startswith(prefix):
                if isinstance(responses, httpx.Response):
                    return responses
                index = calls.get(prefix, 0)
                calls[prefix] = index + 1
                return responses[min(index, len(responses) - 1)]
        return httpx.Response(404)

    return handler


def test_fetches_and_parses_listing_and_detail(tmp_path):
    handler = site(
        {
            "/?sort=latest": httpx.Response(200, text=LISTING_HTML),
            "/movies/101": httpx.Response(200, text=DETAIL_HTML),
        }
    )
    settings = make_settings(tmp_path)

    async def action(client: Oreno3dClient):  # type: ignore[no-untyped-def]
        return await client.fetch_listing_page(1), await client.fetch_movie_detail(101)

    listing, detail = run(settings, handler, action)
    assert [item.source_site_id for item in listing.items] == [101, 102]
    assert detail.title == "Alpha Signal"


def test_not_found_and_placeholder_are_terminal(tmp_path):
    handler = site(
        {
            "/movies/1": httpx.Response(404),
            "/movies/2": httpx.Response(410),
            "/movies/3": httpx.Response(200, text=DETAIL_HTML_PLACEHOLDER),
        }
    )
    settings = make_settings(tmp_path)
    for movie_id, error in ((1, RemoteNotFoundError), (2, RemoteNotFoundError), (3, RemoteUnavailableError)):
        sleeps = Recorder()
        with pytest.raises(error):
            run(settings, handler, lambda c, m=movie_id: c.fetch_movie_detail(m), sleeps)
        assert sleeps.sleeps == []  # never retried


def test_client_errors_are_not_retried(tmp_path):
    handler = site({"/movies/5": [httpx.Response(403), httpx.Response(200, text=DETAIL_HTML)]})
    sleeps = Recorder()
    with pytest.raises(RemoteClientError) as excinfo:
        run(make_settings(tmp_path), handler, lambda c: c.fetch_movie_detail(5), sleeps)
    assert excinfo.value.status_code == 403
    assert sleeps.sleeps == []


def test_server_errors_are_retried_with_jittered_backoff(tmp_path):
    handler = site(
        {"/movies/101": [httpx.Response(502), httpx.Response(500), httpx.Response(200, text=DETAIL_HTML)]}
    )
    sleeps = Recorder()
    settings = make_settings(tmp_path, backoff_base_seconds=1.0, backoff_max_seconds=60.0)

    async def action(client: Oreno3dClient):  # type: ignore[no-untyped-def]
        detail = await client.fetch_movie_detail(101)
        return detail, client.stats

    detail, stats = run(settings, handler, action, sleeps)
    assert detail.title == "Alpha Signal"
    assert len(sleeps.sleeps) == 2
    assert 0 <= sleeps.sleeps[0] <= 1.0
    assert 0 <= sleeps.sleeps[1] <= 2.0
    assert stats.retries == 2
    assert stats.status_codes[502] == 1


def test_429_honours_retry_after_and_slows_down(tmp_path):
    handler = site(
        {
            "/movies/101": [
                httpx.Response(429, headers={"Retry-After": "7"}),
                httpx.Response(200, text=DETAIL_HTML),
            ]
        }
    )
    sleeps = Recorder()
    settings = make_settings(tmp_path, request_rate=4.0)

    async def action(client: Oreno3dClient):  # type: ignore[no-untyped-def]
        await client.fetch_movie_detail(101)
        return client._limiter.rate, client.stats.throttled

    rate, throttled = run(settings, handler, action, sleeps)
    assert sleeps.sleeps == [7.0]
    assert rate == 2.0  # halved
    assert throttled == 1


def test_gives_up_when_retry_after_is_too_long(tmp_path):
    handler = site({"/movies/101": httpx.Response(503, headers={"Retry-After": "86400"})})
    sleeps = Recorder()
    with pytest.raises(RetriesExhaustedError, match="HTTP 503"):
        run(make_settings(tmp_path), handler, lambda c: c.fetch_movie_detail(101), sleeps)
    assert sleeps.sleeps == []


def test_timeouts_exhaust_retries(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.ReadTimeout("slow", request=request)

    sleeps = Recorder()
    with pytest.raises(RetriesExhaustedError, match="ReadTimeout") as excinfo:
        run(make_settings(tmp_path, request_retries=2), handler, lambda c: c.fetch_movie_detail(1), sleeps)
    assert len(sleeps.sleeps) == 2
    assert "3 attempts" in str(excinfo.value)


def test_robots_disallow_and_crawl_delay(tmp_path):
    robots = "User-agent: *\nDisallow: /movies/666\nCrawl-delay: 2\n"
    handler = site({"/movies/": httpx.Response(200, text=DETAIL_HTML)}, robots=robots)

    async def action(client: Oreno3dClient):  # type: ignore[no-untyped-def]
        with pytest.raises(RobotsDisallowedError):
            await client.fetch_movie_detail(666)
        await client.fetch_movie_detail(101)
        return client._limiter.max_rate

    assert run(make_settings(tmp_path), handler, action) == 0.5


def test_robots_can_be_disabled(tmp_path):
    handler = site({"/movies/": httpx.Response(200, text=DETAIL_HTML)}, robots="User-agent: *\nDisallow: /\n")
    settings = make_settings(tmp_path, respect_robots=False)
    assert run(settings, handler, lambda c: c.fetch_movie_detail(101)).title == "Alpha Signal"


def test_honest_user_agent_is_sent(tmp_path):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(404)

    with pytest.raises(RemoteNotFoundError):
        run(make_settings(tmp_path), handler, lambda c: c.fetch_movie_detail(1))
    assert seen
    assert all(ua.startswith("search-iwara/") and "github.com" in ua for ua in seen)


def test_missing_proxy_dependency_is_reported_clearly(tmp_path, monkeypatch):
    def broken(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ImportError("Using SOCKS proxy, but the 'socksio' package is not installed.")

    monkeypatch.setattr(httpx, "AsyncClient", broken)
    with pytest.raises(CrawlerConfigError, match="SEARCH_IWARA_TRUST_ENV"):
        Oreno3dClient(make_settings(tmp_path))


def test_socks_proxy_setting_is_accepted(tmp_path):
    settings = make_settings(tmp_path, proxy="socks5://127.0.0.1:1080")

    async def build() -> None:
        client = Oreno3dClient(settings)
        await client.aclose()

    asyncio.run(build())


@pytest.mark.parametrize(
    ("header", "expected"),
    [(None, None), ("", None), ("12", 12.0), ("soon", None)],
)
def test_parse_retry_after_seconds(header, expected):  # type: ignore[no-untyped-def]
    assert parse_retry_after(header) == expected


def test_parse_retry_after_http_date():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    header = format_datetime(now + timedelta(seconds=30), usegmt=True)
    assert parse_retry_after(header, now=now.timestamp()) == pytest.approx(30.0)
    past = format_datetime(now - timedelta(seconds=30), usegmt=True)
    assert parse_retry_after(past, now=now.timestamp()) == 0.0


def test_backoff_is_capped_full_jitter():
    rng = random.Random(1)
    delays = [backoff_delay(attempt, base=1.0, cap=10.0, rng=rng) for attempt in range(10)]
    assert all(0 <= delay <= 10.0 for delay in delays)
    assert max(delays) > 1.0


def test_rate_limiter_aimd_and_spacing():
    limiter = AdaptiveRateLimiter(10.0)
    limiter.penalize()
    limiter.penalize()
    assert limiter.rate == 2.5
    for _ in range(40):
        limiter.reward()
    assert limiter.rate == 4.5
    for _ in range(10):
        limiter.penalize()
    assert limiter.rate == 0.1  # floor
    limiter.cap(0.05)
    assert limiter.max_rate == 0.05

    fast = AdaptiveRateLimiter(20.0)

    async def burst() -> float:
        loop = asyncio.get_running_loop()
        start = loop.time()
        await asyncio.gather(*(fast.acquire() for _ in range(5)))
        return loop.time() - start

    assert asyncio.run(burst()) >= 0.18  # 5 tokens at 20/s -> >= 4 intervals of 50ms


# --- robots.txt per RFC 9309 ------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_robots_4xx_allows_everything(tmp_path, status):  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(status)
        return httpx.Response(200, text=DETAIL_HTML)

    async def action(client: Oreno3dClient):  # type: ignore[no-untyped-def]
        await client.fetch_movie_detail(101)
        await client.fetch_movie_detail(101)

    run(make_settings(tmp_path), handler, action)
    assert calls.count("/robots.txt") == 1  # cached


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.Response(429)])
def test_robots_unreachable_disallows_and_is_cached(tmp_path, response):  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return response if request.url.path == "/robots.txt" else httpx.Response(200, text=DETAIL_HTML)

    async def action(client: Oreno3dClient):  # type: ignore[no-untyped-def]
        for _ in range(2):
            with pytest.raises(RobotsUnavailableError, match="RFC 9309"):
                await client.fetch_movie_detail(101)

    run(make_settings(tmp_path, request_retries=1), handler, action)
    assert "/movies/101" not in calls  # nothing was crawled
    assert calls.count("/robots.txt") == 2  # one attempt + one retry, then cached


def test_retry_after_with_unicode_digits_is_ignored() -> None:
    assert parse_retry_after("²") is None
