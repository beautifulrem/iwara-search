from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .crawler import Oreno3dClient, RemoteNotFoundError
from .db import Repository
from .models import ListUpsertResult
from .utils import chunked


@dataclass(slots=True)
class SyncSummary:
    pages_checked: int = 0
    movies_seen: int = 0
    new_movies: int = 0
    changed_movies: int = 0
    details_fetched: int = 0
    missing_movies: int = 0
    failed_details: int = 0


class SyncService:
    def __init__(self, repo: Repository, client: Oreno3dClient):
        self.repo = repo
        self.client = client

    async def sync_full(self, *, start_page: int | None = None, max_pages: int | None = None) -> SyncSummary:
        summary = SyncSummary()
        target_last_page = self.repo.get_state_int("sync_full_target_last_page", 0)
        last_completed = self.repo.get_state_int("sync_full_last_completed_page", 0)

        if start_page is None:
            if target_last_page and last_completed >= target_last_page:
                current_page = 1
            else:
                current_page = max(last_completed + 1, 1)
        else:
            current_page = max(start_page, 1)

        first_listing = await self.client.fetch_listing_page(current_page)
        target_last_page = first_listing.last_page
        with self.repo.transaction():
            self.repo.set_state("sync_full_target_last_page", target_last_page)
        page_queue = [first_listing]

        while page_queue:
            listing = page_queue.pop(0)
            ids_for_details, _ = self._persist_listing(listing, summary)
            summary.pages_checked += 1
            await self._sync_movie_details(ids_for_details, summary)
            with self.repo.transaction():
                self.repo.set_state("sync_full_last_completed_page", listing.page)

            if max_pages is not None and summary.pages_checked >= max_pages:
                break
            next_page = listing.page + 1
            if next_page <= target_last_page:
                page_queue.append(await self.client.fetch_listing_page(next_page))

        pending_ids = self.repo.get_movies_needing_detail()
        await self._sync_movie_details(pending_ids, summary)
        return summary

    async def sync_latest(self, *, stable_page_limit: int = 3, max_pages: int | None = None) -> SyncSummary:
        summary = SyncSummary()
        stable_pages = 0
        page = 1
        detail_candidates: list[int] = []

        while stable_pages < stable_page_limit:
            listing = await self.client.fetch_listing_page(page)
            ids_for_details, page_changed = self._persist_listing(listing, summary)
            detail_candidates.extend(ids_for_details)
            summary.pages_checked += 1

            if page_changed:
                stable_pages = 0
            else:
                stable_pages += 1

            with self.repo.transaction():
                self.repo.set_state("sync_latest_last_checked_page", page)

            if max_pages is not None and summary.pages_checked >= max_pages:
                break
            if page >= listing.last_page:
                break
            page += 1

        extra_failed = self.repo.get_failed_movie_ids()
        merged = list(dict.fromkeys([*detail_candidates, *extra_failed]))
        await self._sync_movie_details(merged, summary)
        return summary

    def _persist_listing(self, listing, summary: SyncSummary) -> tuple[list[int], bool]:
        detail_ids: list[int] = []
        page_changed = False
        with self.repo.transaction():
            for item in listing.items:
                result = self.repo.upsert_movie_list_item(item)
                summary.movies_seen += 1
                if result.is_new:
                    summary.new_movies += 1
                    page_changed = True
                elif result.list_changed:
                    summary.changed_movies += 1
                    page_changed = True
                if result.needs_detail:
                    detail_ids.append(item.source_site_id)
        return detail_ids, page_changed

    async def _sync_movie_details(self, source_ids: list[int], summary: SyncSummary) -> None:
        unique_ids = list(dict.fromkeys(source_ids))
        for batch in chunked(unique_ids, 12):
            await asyncio.gather(*(self._sync_one_movie_detail(source_id, summary) for source_id in batch))

    async def _sync_one_movie_detail(self, source_site_id: int, summary: SyncSummary) -> None:
        url = f"https://oreno3d.com/movies/{source_site_id}"
        try:
            detail = await self.client.fetch_movie_detail(source_site_id)
            with self.repo.transaction():
                self.repo.apply_movie_detail(detail)
                self.repo.clear_error(entity_type="movie", entity_id=str(source_site_id), operation="detail")
            summary.details_fetched += 1
        except RemoteNotFoundError:
            with self.repo.transaction():
                self.repo.mark_movie_missing(source_site_id, url)
                self.repo.clear_error(entity_type="movie", entity_id=str(source_site_id), operation="detail")
            summary.missing_movies += 1
        except Exception as exc:
            with self.repo.transaction():
                self.repo.log_error(
                    entity_type="movie",
                    entity_id=str(source_site_id),
                    operation="detail",
                    url=url,
                    error_message=str(exc),
                )
            summary.failed_details += 1
