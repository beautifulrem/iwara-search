"""A polite, resilient HTTP client for oreno3d.com.

Politeness and resilience are layered, from the outside in:

1. ``robots.txt`` is fetched once and honoured (including ``Crawl-delay``).
2. A process-wide token bucket caps the request *rate*; a semaphore caps *concurrency*.
3. The bucket adapts (AIMD): every 429/503 halves the rate, sustained success slowly
   restores it — the same idea as Scrapy's AutoThrottle.
4. Errors are classified: 404/410 are terminal "not found", other 4xx are terminal client
   errors, while 408/425/429/5xx, timeouts and transport errors are retried with capped
   exponential backoff + full jitter, preferring the server's ``Retry-After`` when given.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Self
from urllib.robotparser import RobotFileParser

import httpx

from .config import Settings
from .models import CrawlerStats, ListingPage, MovieDetail
from .parsers import DetailUnavailableError, parse_listing_page, parse_movie_detail
from .utils import ASCII_DIGITS_RE

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
THROTTLE_STATUS = frozenset({429, 503})
NOT_FOUND_STATUS = frozenset({404, 410})
MIN_RATE = 0.1


class CrawlerError(Exception):
    """Base class for crawler failures."""


class CrawlerConfigError(CrawlerError):
    """The client cannot be constructed with the current configuration."""


class RemoteNotFoundError(CrawlerError):
    pass


class RemoteUnavailableError(CrawlerError):
    pass


class RemoteClientError(CrawlerError):
    """A non-retryable 4xx response (e.g. 403)."""

    def __init__(self, url: str, status_code: int):
        super().__init__(f"HTTP {status_code} for {url}")
        self.status_code = status_code


class RetriesExhaustedError(CrawlerError):
    def __init__(self, url: str, attempts: int, last_error: str):
        super().__init__(f"gave up on {url} after {attempts} attempts: {last_error}")
        self.last_error = last_error


class RobotsDisallowedError(CrawlerError):
    pass


class RobotsUnavailableError(CrawlerError):
    """robots.txt could not be fetched (5xx/429/network): RFC 9309 says assume full disallow."""


def parse_retry_after(value: str | None, *, now: float | None = None) -> float | None:
    """Parse ``Retry-After`` (delta-seconds or HTTP-date) into seconds from now."""

    if not value:
        return None
    value = value.strip()
    if ASCII_DIGITS_RE.fullmatch(value):
        return float(value)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    current = datetime.now(UTC).timestamp() if now is None else now
    return max(0.0, moment.timestamp() - current)


def backoff_delay(attempt: int, *, base: float, cap: float, rng: random.Random) -> float:
    """Full-jitter exponential backoff (AWS architecture blog): U(0, min(cap, base·2^n))."""

    return rng.uniform(0.0, min(cap, base * (2**attempt)))


class AdaptiveRateLimiter:
    """Token bucket (burst of 1) whose rate follows additive-increase/multiplicative-decrease."""

    def __init__(self, rate: float) -> None:
        self.max_rate = rate
        self.rate = rate
        self._next_slot = 0.0
        self._lock = asyncio.Lock()
        self._successes = 0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + 1.0 / self.rate
        if wait > 0:
            await asyncio.sleep(wait)

    def penalize(self) -> None:
        self.rate = max(MIN_RATE, self.rate / 2)
        self._successes = 0
        logger.warning("throttled by server; request rate lowered to %.2f req/s", self.rate)

    def reward(self) -> None:
        if self.rate >= self.max_rate:
            return
        self._successes += 1
        if self._successes >= 20:
            self._successes = 0
            self.rate = min(self.max_rate, self.rate + max(0.1, self.max_rate * 0.1))

    def cap(self, rate: float) -> None:
        self.max_rate = min(self.max_rate, rate)
        self.rate = min(self.rate, self.max_rate)


class Oreno3dClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        rng: random.Random | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.settings = settings
        self.base_url = settings.base_url
        self.stats = CrawlerStats()
        self._rng = rng or random.Random()  # noqa: S311 - jitter, not cryptography
        self._sleep: Callable[[float], Awaitable[None]] = sleep or asyncio.sleep
        try:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": settings.user_agent,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "ja,en;q=0.8",
                },
                follow_redirects=True,
                timeout=httpx.Timeout(settings.request_timeout_seconds, connect=10.0),
                limits=httpx.Limits(
                    max_connections=settings.request_concurrency,
                    max_keepalive_connections=settings.request_concurrency,
                ),
                http2=settings.http2,
                proxy=settings.proxy,
                trust_env=settings.trust_env,
                transport=transport,
            )
        except ImportError as exc:  # e.g. SOCKS proxy in the environment without socksio
            raise CrawlerConfigError(
                f"HTTP client dependency missing ({exc}). Reinstall with `uv sync` so that "
                "httpx[socks,http2] is present, or set SEARCH_IWARA_TRUST_ENV=false / "
                "SEARCH_IWARA_PROXY to bypass the environment proxy."
            ) from exc
        self._semaphore = asyncio.Semaphore(settings.request_concurrency)
        self._limiter = AdaptiveRateLimiter(settings.request_rate)
        self._robots: RobotFileParser | None = None
        self._robots_error: RobotsUnavailableError | None = None
        self._robots_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # --- URLs --------------------------------------------------------------------------------

    def listing_url(self, page: int) -> str:
        return f"{self.base_url}/?sort=latest&page={page}"

    def movie_url(self, source_site_id: int) -> str:
        return f"{self.base_url}/movies/{source_site_id}"

    # --- robots.txt --------------------------------------------------------------------------

    async def _ensure_robots(self) -> RobotFileParser | None:
        """Fetch robots.txt once and cache the outcome, following RFC 9309 §2.3.1:

        * 2xx — parse and obey (including ``Crawl-delay``);
        * 4xx other than 429 ("unavailable") — no restrictions apply;
        * 5xx, 429 or network failure ("unreachable") — assume complete disallow, so the
          run stops with :class:`RobotsUnavailableError` instead of crawling blindly.
        """

        if not self.settings.respect_robots:
            return None
        async with self._robots_lock:
            if self._robots_error is not None:
                raise self._robots_error
            if self._robots is not None:
                return self._robots
            url = f"{self.base_url}/robots.txt"
            parser = RobotFileParser()
            try:
                response = await self._send(url)
                parser.parse(response.text.splitlines())
            except (RemoteNotFoundError, RemoteClientError):
                parser.parse([])
            except CrawlerError as exc:
                self._robots_error = RobotsUnavailableError(
                    f"{url} is unreachable ({exc}); treating the site as disallowed (RFC 9309)"
                )
                raise self._robots_error from exc
            delay = parser.crawl_delay(self.settings.user_agent)
            if delay:
                self._limiter.cap(1.0 / float(delay))
                logger.info("robots.txt crawl-delay %.1fs applied", float(delay))
            self._robots = parser
            return parser

    async def _check_robots(self, url: str) -> None:
        robots = await self._ensure_robots()
        if robots is not None and not robots.can_fetch(self.settings.user_agent, url):
            raise RobotsDisallowedError(f"robots.txt disallows {url}")

    # --- transport ---------------------------------------------------------------------------

    async def _send(self, url: str) -> httpx.Response:
        """GET with rate limiting, error classification and jittered retries."""

        attempts = self.settings.request_retries + 1
        last_error = "unknown error"
        for attempt in range(attempts):
            retry_after: float | None = None
            await self._limiter.acquire()
            try:
                async with self._semaphore:
                    self.stats.requests += 1
                    response = await self._client.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                status = response.status_code
                self.stats.status_codes[status] += 1
                if status < 400:
                    self._limiter.reward()
                    return response
                if status in NOT_FOUND_STATUS:
                    raise RemoteNotFoundError(url)
                if status not in RETRYABLE_STATUS:
                    raise RemoteClientError(url, status)
                last_error = f"HTTP {status}"
                if status in THROTTLE_STATUS:
                    self.stats.throttled += 1
                    self._limiter.penalize()
                    retry_after = parse_retry_after(response.headers.get("Retry-After"))

            if attempt + 1 >= attempts:
                break
            delay = backoff_delay(
                attempt,
                base=self.settings.backoff_base_seconds,
                cap=self.settings.backoff_max_seconds,
                rng=self._rng,
            )
            if retry_after is not None:
                if retry_after > self.settings.backoff_max_seconds * 5:
                    break  # the server asked us to go away for a long time; give up this URL
                delay = max(delay, retry_after)
            self.stats.retries += 1
            logger.info(
                "retrying %s in %.2fs (%s, attempt %d/%d)", url, delay, last_error, attempt + 1, attempts
            )
            await self._sleep(delay)
        raise RetriesExhaustedError(url, attempts, last_error)

    async def fetch_text(self, url: str) -> str:
        await self._check_robots(url)
        response = await self._send(url)
        return response.text

    async def fetch_listing_page(self, page: int) -> ListingPage:
        html = await self.fetch_text(self.listing_url(page))
        return parse_listing_page(html, page=page, base_url=self.base_url)

    async def fetch_movie_detail(self, source_site_id: int) -> MovieDetail:
        url = self.movie_url(source_site_id)
        html = await self.fetch_text(url)
        try:
            return parse_movie_detail(
                html, source_site_id=source_site_id, oreno3d_url=url, base_url=self.base_url
            )
        except DetailUnavailableError as exc:
            raise RemoteUnavailableError(url) from exc
