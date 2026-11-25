"""A polite, resilient HTTP client for oreno3d.com.

Politeness, safety and resilience are layered, from the outside in:

1. ``robots.txt`` is fetched once and honoured (including ``Crawl-delay``) on initial URLs and
   every redirect hop (RFC 9309 §2.3–2.5).
2. Redirects are followed manually (<= 5 hops) only to the configured origin/subdomains over
   HTTP(S), preventing off-origin SSRF or ``robots.txt`` bypasses.
3. Streaming byte caps (2 MiB for ``robots.txt``, 10 MiB for HTML) bound memory against malformed
   or infinite upstream streams.
4. A process-wide token bucket caps the request *rate*; a semaphore caps *concurrency*.
5. The bucket adapts (AIMD): every 429/503 halves the rate, sustained success slowly restores it.
6. Errors are classified: 404/410 are terminal "not found", other 4xx are terminal client errors,
   while 408/425/429/5xx, timeouts and transport errors are retried with capped exponential
   backoff + full jitter, preferring the server's ``Retry-After`` when given.
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
from typing import Final, Self
from urllib.parse import urljoin, urlsplit
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
REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
MIN_RATE = 0.1
MAX_REDIRECTS: Final = 5
MAX_ROBOTS_BYTES: Final = 2 * 1024 * 1024  # >= 500 KiB minimum required by RFC 9309 §2.5
MAX_HTML_BYTES: Final = 10 * 1024 * 1024


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


class UnsafeRedirectError(CrawlerError):
    """A redirect exceeded hop limits or pointed outside the allowed origin/scheme."""


class ResponseTooLargeError(CrawlerError):
    """An upstream HTTP response exceeded the configured byte ceiling."""


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


def _canonical_domain(hostname: str) -> str:
    host = hostname.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


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
        parsed_base = urlsplit(self.base_url)
        if parsed_base.scheme not in {"http", "https"} or not parsed_base.hostname:
            raise CrawlerConfigError(f"invalid base_url: {self.base_url!r}")
        self._allowed_domain = _canonical_domain(parsed_base.hostname)
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
                follow_redirects=False,
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

    # --- URLs & origin policy ----------------------------------------------------------------

    def listing_url(self, page: int) -> str:
        return f"{self.base_url}/?sort=latest&page={page}"

    def movie_url(self, source_site_id: int) -> str:
        return f"{self.base_url}/movies/{source_site_id}"

    def _validate_target_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise UnsafeRedirectError(f"disallowed URL scheme or missing host: {url!r}")
        if parts.username or parts.password:
            raise UnsafeRedirectError(f"disallowed credentials in URL: {url!r}")
        host = _canonical_domain(parts.hostname)
        if host != self._allowed_domain and not host.endswith("." + self._allowed_domain):
            raise UnsafeRedirectError(
                f"refusing off-origin request to {parts.hostname!r} (expected {self._allowed_domain!r})"
            )

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
                text = await self._fetch_with_redirects(url, check_robots=False, max_bytes=MAX_ROBOTS_BYTES)
                parser.parse(text.splitlines())
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

    @staticmethod
    async def _read_bounded_body(response: httpx.Response, *, url: str, max_bytes: int) -> bytes:
        declared_len = response.headers.get("Content-Length")
        if declared_len and declared_len.isdigit() and int(declared_len) > max_bytes:
            raise ResponseTooLargeError(f"{url} Content-Length {declared_len} exceeds {max_bytes} bytes")
        chunks: list[bytes] = []
        received = 0
        async for chunk in response.aiter_bytes():
            received += len(chunk)
            if received > max_bytes:
                raise ResponseTooLargeError(f"{url} response body exceeded {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _send_bounded(
        self, url: str, *, max_bytes: int
    ) -> tuple[int, httpx.Headers, str | None, bytes]:
        """Single-hop GET with rate limiting, bounded streaming read, and jittered retries."""

        attempts = self.settings.request_retries + 1
        last_error = "unknown error"
        for attempt in range(attempts):
            retry_after: float | None = None
            await self._limiter.acquire()
            try:
                async with self._semaphore:
                    self.stats.requests += 1
                    async with self._client.stream("GET", url) as response:
                        status = response.status_code
                        headers = response.headers
                        encoding = response.encoding
                        self.stats.status_codes[status] += 1
                        if status in REDIRECT_STATUS:
                            self._limiter.reward()
                            return status, headers, encoding, b""
                        if status < 400:
                            body = await self._read_bounded_body(response, url=url, max_bytes=max_bytes)
                            self._limiter.reward()
                            return status, headers, encoding, body
                        if status in NOT_FOUND_STATUS:
                            raise RemoteNotFoundError(url)
                        if status not in RETRYABLE_STATUS:
                            raise RemoteClientError(url, status)
                        last_error = f"HTTP {status}"
                        if status in THROTTLE_STATUS:
                            self.stats.throttled += 1
                            self._limiter.penalize()
                            retry_after = parse_retry_after(headers.get("Retry-After"))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"

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

    async def _fetch_with_redirects(self, url: str, *, check_robots: bool, max_bytes: int) -> str:
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            self._validate_target_url(current)
            if check_robots:
                await self._check_robots(current)
            status, headers, encoding, body = await self._send_bounded(current, max_bytes=max_bytes)
            if status in REDIRECT_STATUS:
                if hop >= MAX_REDIRECTS:
                    raise UnsafeRedirectError(f"exceeded {MAX_REDIRECTS} redirects starting from {url}")
                location = headers.get("Location", "").strip()
                if not location:
                    raise UnsafeRedirectError(f"redirect HTTP {status} from {current} missing Location")
                current = urljoin(current, location)
                continue
            codec = encoding or "utf-8"
            try:
                return body.decode(codec, errors="replace")
            except LookupError:
                return body.decode("utf-8", errors="replace")
        raise UnsafeRedirectError(
            f"exceeded {MAX_REDIRECTS} redirects starting from {url}"
        )  # pragma: no cover

    async def fetch_text(self, url: str) -> str:
        return await self._fetch_with_redirects(url, check_robots=True, max_bytes=MAX_HTML_BYTES)

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
