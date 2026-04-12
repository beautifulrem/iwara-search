from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from .crawler import Oreno3dClient, RemoteNotFoundError, RemoteUnavailableError
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


@dataclass(slots=True)
class DetailBatchProgress:
    mode: str
    label: str
    total_items: int
    batch_pages: int
    pages_completed_before_batch: int
    total_pages: int | None
    current_page: int


class SyncProgressReporter(Protocol):
    def on_page_plan(self, *, mode: str, current_page: int, total_pages: int | None) -> None: ...

    def on_page_processed(
        self,
        *,
        mode: str,
        page: int,
        pages_checked: int,
        total_pages: int | None,
        stable_pages: int | None = None,
        stable_page_limit: int | None = None,
    ) -> None: ...

    def on_detail_batch_start(self, *, batch: DetailBatchProgress) -> None: ...

    def on_detail_item_done(self, *, batch: DetailBatchProgress, processed_items: int) -> None: ...


class SyncService:
    def __init__(self, repo: Repository, client: Oreno3dClient):
        self.repo = repo
        self.client = client

    async def sync_full(
        self,
        *,
        start_page: int | None = None,
        max_pages: int | None = None,
        progress: SyncProgressReporter | None = None,
    ) -> SyncSummary:
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
        initial_completed_pages = current_page - 1

        first_listing = await self.client.fetch_listing_page(current_page)
        target_last_page = first_listing.last_page
        final_page = target_last_page
        if max_pages is not None:
            final_page = min(target_last_page, current_page + max_pages - 1)
        if progress is not None:
            progress.on_page_plan(mode="full", current_page=current_page, total_pages=final_page)
        with self.repo.transaction():
            self.repo.set_state("sync_full_target_last_page", target_last_page)
        next_page = current_page
        prefetched_first = first_listing

        while next_page <= final_page:
            batch_end = min(final_page, next_page + self.client.settings.listing_prefetch_pages - 1)
            pages = list(range(next_page, batch_end + 1))

            listings = []
            remaining_pages = pages
            if prefetched_first is not None and prefetched_first.page == next_page:
                listings.append(prefetched_first)
                remaining_pages = pages[1:]
                prefetched_first = None

            if remaining_pages:
                fetched = await asyncio.gather(
                    *(self.client.fetch_listing_page(page_number) for page_number in remaining_pages)
                )
                listings.extend(fetched)

            listings.sort(key=lambda listing: listing.page)

            detail_ids_for_batch: list[int] = []
            last_processed_page: int | None = None
            for listing in listings:
                ids_for_details, _ = self._persist_listing(listing, summary)
                detail_ids_for_batch.extend(ids_for_details)
                summary.pages_checked += 1
                last_processed_page = listing.page
                with self.repo.transaction():
                    self.repo.set_state("sync_full_last_completed_page", listing.page)

                if max_pages is not None and summary.pages_checked >= max_pages:
                    break

            label = (
                f"pages {listings[0].page}-{listings[-1].page} details"
                if listings
                else "page details"
            )
            batch_progress = DetailBatchProgress(
                mode="full",
                label=label,
                total_items=len(detail_ids_for_batch),
                batch_pages=len(listings),
                pages_completed_before_batch=initial_completed_pages + summary.pages_checked - len(listings),
                total_pages=final_page,
                current_page=last_processed_page or next_page,
            )
            await self._sync_movie_details(
                detail_ids_for_batch,
                summary,
                progress=progress,
                batch=batch_progress,
            )
            if progress is not None and last_processed_page is not None:
                progress.on_page_processed(
                    mode="full",
                    page=last_processed_page,
                    pages_checked=summary.pages_checked,
                    total_pages=final_page,
                )

            if max_pages is not None and summary.pages_checked >= max_pages:
                break
            next_page = batch_end + 1

        pending_ids = self.repo.get_movies_needing_detail()
        pending_batch = DetailBatchProgress(
            mode="full",
            label="pending details",
            total_items=len(pending_ids),
            batch_pages=0,
            pages_completed_before_batch=initial_completed_pages + summary.pages_checked,
            total_pages=final_page,
            current_page=initial_completed_pages + summary.pages_checked if summary.pages_checked > 0 else current_page,
        )
        await self._sync_movie_details(
            pending_ids,
            summary,
            progress=progress,
            batch=pending_batch,
        )
        return summary

    async def sync_latest(
        self,
        *,
        stable_page_limit: int = 3,
        max_pages: int | None = None,
        progress: SyncProgressReporter | None = None,
    ) -> SyncSummary:
        summary = SyncSummary()
        stable_pages = 0
        page = 1
        detail_candidates: list[int] = []
        if progress is not None:
            progress.on_page_plan(mode="latest", current_page=page, total_pages=max_pages)

        while stable_pages < stable_page_limit:
            listing = await self.client.fetch_listing_page(page)
            ids_for_details, page_changed = self._persist_listing(listing, summary)
            detail_candidates.extend(ids_for_details)
            summary.pages_checked += 1

            if page_changed:
                stable_pages = 0
            else:
                stable_pages += 1

            if progress is not None:
                progress.on_page_processed(
                    mode="latest",
                    page=page,
                    pages_checked=summary.pages_checked,
                    total_pages=max_pages,
                    stable_pages=stable_pages,
                    stable_page_limit=stable_page_limit,
                )

            with self.repo.transaction():
                self.repo.set_state("sync_latest_last_checked_page", page)

            if max_pages is not None and summary.pages_checked >= max_pages:
                break
            if page >= listing.last_page:
                break
            page += 1

        extra_failed = self.repo.get_failed_movie_ids()
        merged = list(dict.fromkeys([*detail_candidates, *extra_failed]))
        batch_progress = DetailBatchProgress(
            mode="latest",
            label="latest detail sync",
            total_items=len(merged),
            batch_pages=0,
            pages_completed_before_batch=summary.pages_checked,
            total_pages=max_pages,
            current_page=page,
        )
        await self._sync_movie_details(
            merged,
            summary,
            progress=progress,
            batch=batch_progress,
        )
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

    async def _sync_movie_details(
        self,
        source_ids: list[int],
        summary: SyncSummary,
        *,
        progress: SyncProgressReporter | None = None,
        batch: DetailBatchProgress,
    ) -> None:
        unique_ids = list(dict.fromkeys(source_ids))
        total_items = len(unique_ids)
        if progress is not None:
            progress.on_detail_batch_start(batch=batch)
        processed_items = 0
        for detail_group in chunked(unique_ids, self.client.settings.detail_batch_size):
            tasks = [asyncio.create_task(self._sync_one_movie_detail(source_id, summary)) for source_id in detail_group]
            for task in asyncio.as_completed(tasks):
                await task
                processed_items += 1
                if progress is not None:
                    progress.on_detail_item_done(
                        batch=batch,
                        processed_items=processed_items,
                    )

    async def _sync_one_movie_detail(self, source_site_id: int, summary: SyncSummary) -> None:
        url = f"https://oreno3d.com/movies/{source_site_id}"
        try:
            detail = await self.client.fetch_movie_detail(source_site_id)
            with self.repo.transaction():
                self.repo.apply_movie_detail(detail)
                self.repo.clear_error(entity_type="movie", entity_id=str(source_site_id), operation="detail")
            summary.details_fetched += 1
        except (RemoteNotFoundError, RemoteUnavailableError):
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
