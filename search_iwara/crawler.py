from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from .config import Settings, get_settings
from .models import ListingPage, MovieDetail
from .parsers import parse_listing_page, parse_movie_detail
from .utils import BASE_URL


class RemoteNotFoundError(Exception):
    pass


@dataclass(slots=True)
class FetchResponse:
    url: str
    status_code: int
    text: str


class Oreno3dClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
            timeout=self.settings.request_timeout_seconds,
        )
        self._semaphore = asyncio.Semaphore(self.settings.request_concurrency)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "Oreno3dClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def _get(self, url: str) -> FetchResponse:
        async with self._semaphore:
            last_error: Exception | None = None
            for attempt in range(self.settings.request_retries):
                try:
                    response = await self._client.get(url)
                    if response.status_code == 404:
                        raise RemoteNotFoundError(url)
                    if response.status_code >= 500 or response.status_code == 429:
                        response.raise_for_status()
                    await asyncio.sleep(self.settings.request_delay_seconds)
                    return FetchResponse(url=str(response.url), status_code=response.status_code, text=response.text)
                except RemoteNotFoundError:
                    raise
                except httpx.HTTPError as exc:
                    last_error = exc
                    backoff = self.settings.request_delay_seconds * (attempt + 1)
                    await asyncio.sleep(backoff)
            assert last_error is not None
            raise last_error

    async def fetch_listing_page(self, page: int) -> ListingPage:
        url = f"{BASE_URL}/?sort=latest&page={page}"
        response = await self._get(url)
        return parse_listing_page(response.text, page=page)

    async def fetch_movie_detail(self, source_site_id: int) -> MovieDetail:
        url = f"{BASE_URL}/movies/{source_site_id}"
        response = await self._get(url)
        return parse_movie_detail(response.text, source_site_id=source_site_id, oreno3d_url=url)
