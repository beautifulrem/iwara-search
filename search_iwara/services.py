"""Sync orchestration: listing scan → bounded detail queue → batched writes.

Listing pages are fetched in small prefetch batches and persisted immediately; every movie
that needs details is pushed onto a bounded queue drained by a fixed pool of workers, so
listing scans and detail fetches overlap instead of alternating. Results are written in
group commits. Individual page/detail failures are isolated and recorded with a retry
schedule; a structural change of the site (parser drift) aborts the run loudly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType
from typing import Literal, Protocol, Self

from .config import Settings
from .crawler import CrawlerError, RemoteNotFoundError, RemoteUnavailableError, RobotsUnavailableError
from .models import CrawlerStats, ListingPage, MovieDetail
from .parsers import ParserDriftError
from .storage import CrawlStore
from .utils import utc_now

logger = logging.getLogger(__name__)

SyncMode = Literal["full", "latest"]
STATE_FULL_TARGET = "sync_full_target_last_page"
STATE_FULL_COMPLETED = "sync_full_last_completed_page"
STATE_FULL_ROUND_STARTED = "sync_full_round_started_at"  # when the current full round began at page 1
MAX_RESUME_BACKTRACK_PAGES = 50
STATE_LATEST_CHECKED = "sync_latest_last_checked_page"
MAX_CONSECUTIVE_PAGE_FAILURES = 3


class SyncLockedError(RuntimeError):
    """Another sync already holds the lock for this database."""


class SyncAbortedError(RuntimeError):
    """The run stopped early (e.g. parser drift); partial results were kept."""


class CrawlClient(Protocol):
    stats: CrawlerStats

    def listing_url(self, page: int) -> str: ...

    def movie_url(self, source_site_id: int) -> str: ...

    async def fetch_listing_page(self, page: int) -> ListingPage: ...

    async def fetch_movie_detail(self, source_site_id: int) -> MovieDetail: ...


class SyncProgress(Protocol):
    def on_pages_planned(self, *, mode: SyncMode, first_page: int, last_page: int | None) -> None: ...

    def on_page_done(
        self,
        *,
        mode: SyncMode,
        page: int,
        pages_checked: int,
        stable_pages: int | None,
        stable_limit: int | None,
    ) -> None: ...

    def on_details_queued(self, *, total: int) -> None: ...

    def on_detail_done(self, *, done: int) -> None: ...


@dataclass(slots=True)
class SyncSummary:
    pages_checked: int = 0
    failed_pages: int = 0
    movies_seen: int = 0
    new_movies: int = 0
    changed_movies: int = 0
    details_fetched: int = 0
    missing_movies: int = 0
    failed_details: int = 0
    drift_errors: int = 0

    def counters(self) -> dict[str, int]:
        return asdict(self)

    @property
    def clean(self) -> bool:
        return not (self.failed_pages or self.failed_details or self.drift_errors)


@dataclass(frozen=True, slots=True)
class SyncOptions:
    detail_workers: int = 4
    list_prefetch_pages: int = 4
    commit_every: int = 25
    detail_max_attempts: int = 6
    detail_refresh_window_days: int = 30
    detail_refresh_after_hours: int = 72
    detail_refresh_limit: int = 500
    resume_overlap_pages: int = 1
    drift_abort_threshold: int = 5

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            detail_workers=settings.request_concurrency,
            list_prefetch_pages=settings.list_prefetch_pages,
            detail_max_attempts=settings.detail_max_attempts,
            detail_refresh_window_days=settings.detail_refresh_window_days,
            detail_refresh_after_hours=settings.detail_refresh_after_hours,
            detail_refresh_limit=settings.detail_refresh_limit,
            resume_overlap_pages=settings.resume_overlap_pages,
        )


@contextlib.contextmanager
def sync_lock(db_path: Path) -> Iterator[None]:
    """Exclusive, non-blocking advisory lock so timer and manual syncs never overlap."""

    try:
        import fcntl  # noqa: PLC0415 - POSIX only
    except ImportError:  # pragma: no cover - Windows: best effort, no lock
        yield
        return
    lock_path = db_path.with_name(db_path.name + ".sync.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SyncLockedError(f"another sync is running (lock: {lock_path})") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class _DetailPipeline:
    """Bounded queue + worker pool for detail pages, with group-committed writes."""

    def __init__(
        self,
        store: CrawlStore,
        client: CrawlClient,
        summary: SyncSummary,
        options: SyncOptions,
        progress: SyncProgress | None,
    ) -> None:
        self.store = store
        self.client = client
        self.summary = summary
        self.options = options
        self.progress = progress
        self.queue: asyncio.Queue[int | None] = asyncio.Queue(maxsize=options.detail_workers * 4)
        self.seen: set[int] = set()
        self.done = 0
        self._pending: list[tuple[str, int, MovieDetail | BaseException | None]] = []
        self._workers: list[asyncio.Task[None]] = []
        self.aborted: BaseException | None = None

    async def __aenter__(self) -> Self:
        self._workers = [asyncio.create_task(self._worker()) for _ in range(self.options.detail_workers)]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc is None:
            for _ in self._workers:
                await self.queue.put(None)
            await asyncio.gather(*self._workers)
        else:
            for worker in self._workers:
                worker.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
        self.flush()
        if exc is None and self.aborted is not None:
            raise self.aborted

    async def submit(self, source_ids: list[int]) -> None:
        if self.aborted is not None:
            raise self.aborted
        fresh = [source_id for source_id in source_ids if source_id not in self.seen]
        if not fresh:
            return
        self.seen.update(fresh)
        if self.progress is not None:
            self.progress.on_details_queued(total=len(self.seen))
        for source_id in fresh:
            await self.queue.put(source_id)
            if self.aborted is not None:
                raise self.aborted

    async def _worker(self) -> None:
        # Workers never die early: after an abort they keep draining the queue so that a
        # producer blocked on ``put`` is released and sees the abort in ``submit``.
        while (source_id := await self.queue.get()) is not None:
            if self.aborted is not None:
                continue
            try:
                await self._process(source_id)
            except Exception as exc:  # e.g. a storage failure: stop the run, keep draining
                logger.exception("detail pipeline aborted while handling movie %s", source_id)
                self.aborted = exc

    async def _process(self, source_id: int) -> None:
        try:
            detail = await self.client.fetch_movie_detail(source_id)
            self._pending.append(("ok", source_id, detail))
        except (RemoteNotFoundError, RemoteUnavailableError):
            self._pending.append(("missing", source_id, None))
        except ParserDriftError as exc:
            self.summary.drift_errors += 1
            self._pending.append(("error", source_id, exc))
        except RobotsUnavailableError as exc:
            self.aborted = exc
            return
        except CrawlerError as exc:
            self._pending.append(("error", source_id, exc))
        except Exception as exc:  # unexpected: keep the traceback in the logs, record and move on
            logger.exception("unexpected error while fetching movie %s", source_id)
            self._pending.append(("error", source_id, exc))
        self.done += 1
        if self.progress is not None:
            self.progress.on_detail_done(done=self.done)
        if len(self._pending) >= self.options.commit_every:
            self.flush()
        if self.summary.drift_errors >= self.options.drift_abort_threshold:
            self.aborted = SyncAbortedError("detail pages no longer match the parser (site redesign?)")

    def flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        with self.store.transaction():
            for outcome, source_id, payload in batch:
                entity_id = str(source_id)
                if outcome == "ok" and isinstance(payload, MovieDetail):
                    self.store.apply_movie_detail(payload)
                    self.store.clear_error(entity_type="movie", entity_id=entity_id, operation="detail")
                    self.summary.details_fetched += 1
                elif outcome == "missing":
                    self.store.mark_movie_missing(source_id, self.client.movie_url(source_id))
                    self.store.clear_error(entity_type="movie", entity_id=entity_id, operation="detail")
                    self.summary.missing_movies += 1
                elif isinstance(payload, BaseException):
                    self.store.log_error(
                        entity_type="movie",
                        entity_id=entity_id,
                        operation="detail",
                        url=self.client.movie_url(source_id),
                        error=payload,
                    )
                    self.summary.failed_details += 1
                    logger.warning("detail %s failed: %s: %s", source_id, type(payload).__name__, payload)


class SyncService:
    def __init__(self, store: CrawlStore, client: CrawlClient, options: SyncOptions | None = None) -> None:
        self.store = store
        self.client = client
        self.options = options or SyncOptions()

    # --- shared helpers ----------------------------------------------------------------------

    def _persist_listing(self, listing: ListingPage, summary: SyncSummary) -> tuple[list[int], bool]:
        """Upsert one listing page; returns (ids needing details, page had new movies)."""

        if not listing.items and (listing.page == 1 or listing.page < listing.last_page):
            raise ParserDriftError(f"listing page {listing.page} parsed to zero movies")
        detail_ids: list[int] = []
        has_new = False
        with self.store.transaction():
            for item in listing.items:
                result = self.store.upsert_movie_list_item(item)
                summary.movies_seen += 1
                if result.is_new:
                    summary.new_movies += 1
                    has_new = True
                elif result.list_changed:
                    summary.changed_movies += 1
                if result.needs_detail:
                    detail_ids.append(item.source_site_id)
            self.store.clear_error(entity_type="listing", entity_id=str(listing.page), operation="list")
        return detail_ids, has_new

    def _record_page_failure(self, page: int, error: BaseException, summary: SyncSummary) -> None:
        summary.failed_pages += 1
        logger.warning("listing page %d failed: %s: %s", page, type(error).__name__, error)
        with self.store.transaction():
            self.store.log_error(
                entity_type="listing",
                entity_id=str(page),
                operation="list",
                url=self.client.listing_url(page),
                error=error,
            )

    def _retry_backlog(self) -> list[int]:
        return self.store.retryable_failed_movie_ids(max_attempts=self.options.detail_max_attempts)

    async def _run(self, mode: SyncMode, body: Callable[[SyncSummary], Awaitable[None]]) -> SyncSummary:
        summary = SyncSummary()
        run_id = self.store.start_run(mode)
        status, error = "failed", None
        try:
            await body(summary)
            status = "success" if summary.clean else "partial"
            return summary
        except ParserDriftError as exc:
            summary.drift_errors += 1
            error = f"parser drift: {exc}"
            raise SyncAbortedError(error) from exc
        except asyncio.CancelledError:
            error = "terminated: cancelled by signal"
            raise
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            # Runs on success, failure and SIGTERM alike: close the run record and keep the
            # read models consistent with whatever was committed.
            self.store.finish_run(
                run_id, status=status, counters=summary.counters(), error=error, crawler=self.client.stats
            )
            changed = (
                summary.new_movies
                or summary.changed_movies
                or summary.details_fetched
                or summary.missing_movies
            )
            self.store.refresh_derived(full=bool(changed))

    # --- full sync ---------------------------------------------------------------------------

    async def sync_full(
        self,
        *,
        start_page: int | None = None,
        max_pages: int | None = None,
        progress: SyncProgress | None = None,
    ) -> SyncSummary:
        async def body(summary: SyncSummary) -> None:
            await self._sync_full(summary, start_page=start_page, max_pages=max_pages, progress=progress)

        return await self._run("full", body)

    def _resume_page(self, start_page: int | None) -> int:
        if start_page is not None:
            return start_page
        target = self.store.get_state_int(STATE_FULL_TARGET)
        completed = self.store.get_state_int(STATE_FULL_COMPLETED)
        if not completed or (target and completed >= target):
            return 1
        # Step back a little: deletions upstream shift items towards page 1.
        return max(1, completed + 1 - self.options.resume_overlap_pages)

    async def _align_resume(self, page: int, listing: ListingPage) -> tuple[int, ListingPage]:
        """Walk back until the resume page contains a movie already listed in this full pass.

        The listing is ordered by publish time, not by id, so ids cannot tell where we are.
        What can: every listed movie gets ``list_seen_at``. If *none* of the movies on the resume
        page was seen since the pass started, deletions upstream pushed unseen movies onto earlier
        pages and resuming here would skip them; step back until the pages overlap again.
        Insertions upstream push seen movies *onto* the resume page, so they never cause a step.
        """

        pass_started = self.store.get_state(STATE_FULL_ROUND_STARTED)
        steps = 0
        while (
            pass_started
            and page > 1
            and listing.items
            and not self.store.any_listed_since([item.source_site_id for item in listing.items], pass_started)
            and steps < MAX_RESUME_BACKTRACK_PAGES
        ):
            page -= 1
            steps += 1
            listing = await self.client.fetch_listing_page(page)
        if steps:
            logger.info("resume moved back %d page(s) to stay contiguous", steps, extra={"page": page})
        return page, listing

    async def _sync_full(
        self,
        summary: SyncSummary,
        *,
        start_page: int | None,
        max_pages: int | None,
        progress: SyncProgress | None,
    ) -> None:
        first_page = self._resume_page(start_page)
        if first_page == 1:
            with self.store.transaction():
                self.store.set_state(STATE_FULL_ROUND_STARTED, utc_now())
        first = await self.client.fetch_listing_page(first_page)
        if start_page is None:
            first_page, first = await self._align_resume(first_page, first)
        last_page = first.last_page
        if max_pages is not None:
            last_page = min(last_page, first_page + max_pages - 1)
        with self.store.transaction():
            self.store.set_state(STATE_FULL_TARGET, first.last_page)
        if progress is not None:
            progress.on_pages_planned(mode="full", first_page=first_page, last_page=last_page)

        checkpoint_frozen = False
        async with _DetailPipeline(self.store, self.client, summary, self.options, progress) as pipeline:
            prefetched: dict[int, ListingPage | BaseException] = {first_page: first}
            for batch_start in range(first_page, last_page + 1, self.options.list_prefetch_pages):
                pages = list(
                    range(batch_start, min(last_page, batch_start + self.options.list_prefetch_pages - 1) + 1)
                )
                missing = [page for page in pages if page not in prefetched]
                results = await asyncio.gather(
                    *(self.client.fetch_listing_page(page) for page in missing), return_exceptions=True
                )
                prefetched.update(zip(missing, results, strict=True))
                for page in pages:
                    outcome = prefetched.pop(page)
                    summary.pages_checked += 1
                    if isinstance(outcome, (ParserDriftError, RobotsUnavailableError)):
                        raise outcome
                    if isinstance(outcome, BaseException):
                        if not isinstance(outcome, Exception):
                            raise outcome
                        self._record_page_failure(page, outcome, summary)
                        checkpoint_frozen = True  # resume must revisit the gap
                    else:
                        ids, _ = self._persist_listing(outcome, summary)
                        await pipeline.submit(ids)
                        if not checkpoint_frozen:
                            with self.store.transaction():
                                self.store.set_state(STATE_FULL_COMPLETED, page)
                    if progress is not None:
                        progress.on_page_done(
                            mode="full",
                            page=page,
                            pages_checked=summary.pages_checked,
                            stable_pages=None,
                            stable_limit=None,
                        )
            await pipeline.submit(self.store.movies_missing_detail())
            await pipeline.submit(self._retry_backlog())

    # --- incremental sync --------------------------------------------------------------------

    async def sync_latest(
        self,
        *,
        stable_page_limit: int = 3,
        max_pages: int | None = None,
        progress: SyncProgress | None = None,
    ) -> SyncSummary:
        async def body(summary: SyncSummary) -> None:
            await self._sync_latest(
                summary, stable_page_limit=stable_page_limit, max_pages=max_pages, progress=progress
            )

        return await self._run("latest", body)

    async def _sync_latest(
        self,
        summary: SyncSummary,
        *,
        stable_page_limit: int,
        max_pages: int | None,
        progress: SyncProgress | None,
    ) -> None:
        if progress is not None:
            progress.on_pages_planned(mode="latest", first_page=1, last_page=max_pages)
        stable_pages = 0
        consecutive_failures = 0
        known_last_page: int | None = None  # unknown until a listing page parses
        page = 1
        async with _DetailPipeline(self.store, self.client, summary, self.options, progress) as pipeline:
            while stable_pages < stable_page_limit:
                summary.pages_checked += 1
                try:
                    listing = await self.client.fetch_listing_page(page)
                except (ParserDriftError, RobotsUnavailableError):
                    raise
                except CrawlerError as exc:
                    self._record_page_failure(page, exc, summary)
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_CONSECUTIVE_PAGE_FAILURES:
                        logger.error(
                            "stopping scan after %d consecutive listing failures", consecutive_failures
                        )
                        break
                else:
                    consecutive_failures = 0
                    ids, has_new = self._persist_listing(listing, summary)
                    await pipeline.submit(ids)
                    # "Stable" means no *new* movies: counters on recent pages change constantly.
                    stable_pages = 0 if has_new else stable_pages + 1
                    known_last_page = listing.last_page
                    with self.store.transaction():
                        self.store.set_state(STATE_LATEST_CHECKED, page)
                if progress is not None:
                    progress.on_page_done(
                        mode="latest",
                        page=page,
                        pages_checked=summary.pages_checked,
                        stable_pages=stable_pages,
                        stable_limit=stable_page_limit,
                    )
                if max_pages is not None and summary.pages_checked >= max_pages:
                    break
                if known_last_page is not None and page >= known_last_page:
                    break
                page += 1

            await pipeline.submit(self._retry_backlog())
            await pipeline.submit(
                self.store.stale_detail_ids(
                    window_days=self.options.detail_refresh_window_days,
                    refresh_after_hours=self.options.detail_refresh_after_hours,
                    limit=self.options.detail_refresh_limit,
                )
            )
