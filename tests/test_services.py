from __future__ import annotations

import asyncio
import itertools
from pathlib import Path

import pytest

from search_iwara.crawler import (
    RemoteNotFoundError,
    RemoteUnavailableError,
    RetriesExhaustedError,
    RobotsUnavailableError,
)
from search_iwara.models import CrawlerStats, ListingPage, MovieDetail, MovieListItem, SearchFilters
from search_iwara.parsers import ParserDriftError
from search_iwara.services import (
    SyncAbortedError,
    SyncLockedError,
    SyncOptions,
    SyncService,
    SyncSummary,
    sync_lock,
)
from search_iwara.storage import CrawlStore, SearchStore
from tests.factories import make_detail

PAGE_SIZE = 3


def listing_item(source_id: int, views: int = 1) -> MovieListItem:
    return MovieListItem(
        source_id, f"https://oreno3d.com/movies/{source_id}", f"movie {source_id}", "Creator", None, views, 0
    )


class FakeClient:
    """Serves a newest-first catalogue of ``ids`` split into pages; failures are scriptable."""

    def __init__(
        self,
        ids: list[int],
        *,
        failing_pages: set[int] | None = None,
        failing_details: dict[int, Exception] | None = None,
        views: int = 1,
    ) -> None:
        self.ids = ids
        self.failing_pages = failing_pages or set()
        self.failing_details = failing_details or {}
        self.views = views
        self.page_calls: list[int] = []
        self.detail_calls: list[int] = []
        self.stats = CrawlerStats(requests=7, retries=2, throttled=1)

    @property
    def last_page(self) -> int:
        return max(1, -(-len(self.ids) // PAGE_SIZE))

    def listing_url(self, page: int) -> str:
        return f"https://oreno3d.com/?page={page}"

    def movie_url(self, source_site_id: int) -> str:
        return f"https://oreno3d.com/movies/{source_site_id}"

    async def fetch_listing_page(self, page: int) -> ListingPage:
        self.page_calls.append(page)
        await asyncio.sleep(0)
        if page in self.failing_pages:
            raise RetriesExhaustedError(self.listing_url(page), 3, "HTTP 503")
        chunk = self.ids[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        return ListingPage(page, self.last_page, [listing_item(i, self.views) for i in chunk])

    async def fetch_movie_detail(self, source_site_id: int) -> MovieDetail:
        self.detail_calls.append(source_site_id)
        await asyncio.sleep(0)
        if source_site_id in self.failing_details:
            raise self.failing_details[source_site_id]
        return make_detail(source_site_id, title=f"movie {source_site_id}", tags=[(1, "tag")])


OPTIONS = SyncOptions(detail_workers=2, list_prefetch_pages=2, commit_every=2)


def latest(store: CrawlStore, client: FakeClient, **kwargs: int) -> SyncSummary:
    return asyncio.run(SyncService(store, client, OPTIONS).sync_latest(**kwargs))


def full(store: CrawlStore, client: FakeClient, **kwargs: int) -> SyncSummary:
    return asyncio.run(SyncService(store, client, OPTIONS).sync_full(**kwargs))


def total_movies(store: CrawlStore) -> int:
    return SearchStore(store.conn).search(SearchFilters(), page=1, page_size=50, max_results=1000).total


def runs(store: CrawlStore) -> list[tuple[str, str]]:
    return [(row[0], row[1]) for row in store.conn.execute("SELECT mode, status FROM sync_runs ORDER BY id")]


def test_sync_latest_fetches_new_movies_and_stops_when_stable(store: CrawlStore):
    client = FakeClient(list(range(30, 0, -1)))
    summary = latest(store, client, stable_page_limit=2)
    assert summary.pages_checked == client.last_page  # everything was new, so it ran to the end
    assert summary.new_movies == 30
    assert summary.details_fetched == 30
    assert summary.clean
    assert runs(store) == [("latest", "success")]
    assert total_movies(store) == 30

    # Second run: counters changed on every page, but no *new* ids -> stop after 2 stable pages.
    rerun = FakeClient(list(range(30, 0, -1)), views=99)
    summary = latest(store, rerun, stable_page_limit=2)
    assert rerun.page_calls == [1, 2]
    assert summary.new_movies == 0
    assert summary.changed_movies == 6
    assert rerun.detail_calls == []  # details are only fetched for new/incomplete movies


def test_sync_latest_isolates_failures_and_records_them(store: CrawlStore):
    client = FakeClient(
        list(range(9, 0, -1)),
        failing_pages={2},
        failing_details={
            9: RemoteNotFoundError("gone"),
            8: RemoteUnavailableError("private"),
            7: RetriesExhaustedError("u", 3, "HTTP 503"),
        },
    )
    summary = latest(store, client, stable_page_limit=5)
    assert summary.failed_pages == 1
    assert summary.missing_movies == 2
    assert summary.failed_details == 1
    assert summary.details_fetched == 3  # page 3 still processed after page 2 failed
    assert runs(store) == [("latest", "partial")]
    errors = dict(store.conn.execute("SELECT entity_type || ':' || entity_id, error_type FROM crawl_errors"))
    assert errors == {"listing:2": "RetriesExhaustedError", "movie:7": "RetriesExhaustedError"}


def test_consecutive_listing_failures_stop_the_scan(store: CrawlStore):
    client = FakeClient(list(range(30, 0, -1)), failing_pages={1, 2, 3, 4})
    summary = latest(store, client, stable_page_limit=5)
    assert client.page_calls == [1, 2, 3]
    assert summary.failed_pages == 3


def test_empty_listing_page_is_parser_drift(store: CrawlStore):
    class Drifted(FakeClient):
        async def fetch_listing_page(self, page: int) -> ListingPage:
            return ListingPage(page, 50, [])

    with pytest.raises(SyncAbortedError, match="parser drift"):
        latest(store, Drifted([]))
    assert runs(store) == [("latest", "failed")]


def test_repeated_detail_drift_aborts_without_deadlock(store: CrawlStore):
    ids = list(range(60, 0, -1))
    client = FakeClient(ids, failing_details={i: ParserDriftError("layout") for i in ids})
    options = SyncOptions(detail_workers=2, list_prefetch_pages=2, commit_every=2, drift_abort_threshold=3)
    with pytest.raises(SyncAbortedError):
        asyncio.run(
            asyncio.wait_for(SyncService(store, client, options).sync_latest(stable_page_limit=50), 10)
        )
    assert len(client.detail_calls) < len(ids)  # stopped early
    assert runs(store) == [("latest", "failed")]


def test_failed_details_are_retried_later_with_a_cap(store: CrawlStore):
    flaky = FakeClient([3, 2, 1], failing_details={2: RetriesExhaustedError("u", 3, "timeout")})
    latest(store, flaky, stable_page_limit=1)
    store.conn.execute("UPDATE crawl_errors SET next_retry_at = '2000-01-01T00:00:00+00:00'")

    healed = FakeClient([3, 2, 1])
    summary = latest(store, healed, stable_page_limit=1)
    assert healed.detail_calls == [2]
    assert summary.details_fetched == 1
    assert store.conn.execute("SELECT COUNT(*) FROM crawl_errors").fetchone()[0] == 0


def test_sync_latest_refreshes_stale_recent_details(store: CrawlStore):
    latest(store, FakeClient([3, 2, 1]), stable_page_limit=1)
    store.conn.execute(
        "UPDATE movies SET published_at = strftime('%Y-%m-%d %H:%M', 'now'), "
        "detail_fetched_at = '2000-01-01T00:00:00+00:00' WHERE source_site_id = 2"
    )
    again = FakeClient([3, 2, 1])
    latest(store, again, stable_page_limit=1)
    assert again.detail_calls == [2]


def test_sync_full_resumes_with_overlap_and_restarts_when_done(store: CrawlStore):
    ids = list(range(30, 0, -1))  # 10 pages
    first = FakeClient(ids)
    summary = full(store, first, max_pages=4)
    assert summary.pages_checked == 4
    assert store.get_state_int("sync_full_last_completed_page") == 4

    resumed = FakeClient(ids)
    full(store, resumed)
    assert resumed.page_calls[0] == 4  # completed 4, overlap 1 -> restart at page 4
    assert store.get_state_int("sync_full_last_completed_page") == 10
    assert total_movies(store) == 30

    restart = FakeClient(ids)
    full(store, restart, max_pages=1)
    assert restart.page_calls == [1]  # finished catalogue -> next full run starts over


def test_sync_full_failed_page_freezes_checkpoint(store: CrawlStore):
    client = FakeClient(list(range(15, 0, -1)), failing_pages={3})
    summary = full(store, client)
    assert summary.failed_pages == 1
    assert store.get_state_int("sync_full_last_completed_page") == 2  # page 3 must be revisited


def test_sync_full_picks_up_backlog(store: CrawlStore):
    with store.transaction():
        store.upsert_movie_list_item(listing_item(999))  # listed earlier but never detailed
    client = FakeClient([3, 2, 1])
    full(store, client)
    assert 999 in client.detail_calls


def test_sync_lock_is_exclusive(tmp_path: Path):
    db = tmp_path / "x.sqlite3"
    with sync_lock(db), pytest.raises(SyncLockedError), sync_lock(db):
        pass
    with sync_lock(db):  # released
        pass


def test_options_follow_settings(settings):  # type: ignore[no-untyped-def]
    options = SyncOptions.from_settings(settings)
    assert options.detail_workers == settings.request_concurrency
    assert options.list_prefetch_pages == settings.list_prefetch_pages


# --- round-3 regressions ----------------------------------------------------------------------


def test_run_records_crawler_statistics(store: CrawlStore):
    latest(store, FakeClient([3, 2, 1]), stable_page_limit=1)
    row = store.conn.execute("SELECT requests, retries, throttled, status_codes FROM sync_runs").fetchone()
    assert tuple(row) == (7, 2, 1, "{}")


def test_orphaned_running_rows_are_closed(store: CrawlStore):
    orphan = store.start_run("full")  # simulate a process killed with SIGKILL
    latest(store, FakeClient([1]), stable_page_limit=1)
    row = store.conn.execute("SELECT status, error FROM sync_runs WHERE id = ?", (orphan,)).fetchone()
    assert row["status"] == "failed"
    assert "abandoned" in row["error"]


def test_cancellation_flushes_and_closes_the_run(store: CrawlStore):
    """SIGTERM cancels the main task: pending writes are flushed and the run is marked failed."""

    class Slow(FakeClient):
        async def fetch_movie_detail(self, source_site_id: int) -> MovieDetail:
            if len(self.detail_calls) >= 3:
                await asyncio.sleep(3600)
            return await super().fetch_movie_detail(source_site_id)

    async def scenario() -> None:
        service = SyncService(
            store, Slow(list(range(30, 0, -1))), SyncOptions(detail_workers=1, commit_every=50)
        )
        task = asyncio.create_task(service.sync_latest(stable_page_limit=50))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    row = store.conn.execute("SELECT status, error, details_fetched FROM sync_runs").fetchone()
    assert row["status"] == "failed"
    assert "terminated" in row["error"]
    assert row["details_fetched"] == 3  # buffered below commit_every, flushed on cancel
    assert (
        store.conn.execute("SELECT COUNT(*) FROM movies WHERE detail_fetched_at IS NOT NULL").fetchone()[0]
        == 3
    )


def test_unreachable_robots_aborts_the_run(store: CrawlStore):
    class NoRobots(FakeClient):
        async def fetch_listing_page(self, page: int) -> ListingPage:
            raise RobotsUnavailableError("robots.txt unreachable")

    with pytest.raises(RobotsUnavailableError):
        latest(store, NoRobots([]))
    assert runs(store) == [("latest", "failed")]


def test_quiet_run_only_refreshes_recent_hot_scores(store: CrawlStore):
    latest(store, FakeClient([2, 1]), stable_page_limit=1)
    before = store.conn.execute("SELECT COUNT(*) FROM entity_stats").fetchone()[0]
    store.refresh_derived(full=False)
    assert store.conn.execute("SELECT COUNT(*) FROM entity_stats").fetchone()[0] == before
    assert store.conn.execute("SELECT value FROM app_meta WHERE key = 'derived_refreshed_at'").fetchone()


def publish_ordered(count: int, seed: int = 7) -> list[int]:
    """Ids in listing order like the real site: by publish time, so ids are *not* monotonic
    (tests/fixtures/listing_page.html has 10 increases among 36 ids)."""

    import random

    ids = list(range(1000 + count, 1000, -1))
    rng = random.Random(seed)
    for start in range(0, count, 4):  # local reordering, as with uploads published out of order
        chunk = ids[start : start + 4]
        rng.shuffle(chunk)
        ids[start : start + 4] = chunk
    return ids


def detailed_ids(store: CrawlStore) -> set[int]:
    rows = store.conn.execute("SELECT source_site_id FROM movies WHERE detail_fetched_at IS NOT NULL")
    return {row[0] for row in rows}


def test_fixture_listing_is_not_id_ordered():
    from search_iwara.parsers import parse_listing_page
    from tests.test_parsers import BASE, FIXTURES

    page = parse_listing_page(
        (FIXTURES / "listing_page.html").read_text(encoding="utf-8"), page=1, base_url=BASE
    )
    ids = [item.source_site_id for item in page.items]
    assert any(a < b for a, b in itertools.pairwise(ids))  # why resume cannot compare ids


def test_full_resume_backtracks_when_upstream_deletions_shift_pages(store: CrawlStore):
    ids = publish_ordered(60)  # 20 pages of 3, ids not monotonic
    full(store, FakeClient(ids), max_pages=5)  # listed the first 15
    # Upstream deletes 8 already-listed movies: every later movie moves ~3 pages towards page 1.
    deleted = set(ids[2:10])
    resumed = FakeClient([i for i in ids if i not in deleted])
    full(store, resumed)
    assert resumed.page_calls[0] == 5  # completed 5, overlap 1 ...
    assert min(resumed.page_calls) < 5  # ... then walked back to where it overlaps again
    assert set(ids) - deleted <= detailed_ids(store)  # nothing was skipped


def test_full_resume_does_not_backtrack_after_insertions(store: CrawlStore):
    ids = publish_ordered(60)
    full(store, FakeClient(ids), max_pages=5)
    newer = list(range(5000, 5006))  # six new uploads push everything two pages further
    resumed = FakeClient(newer + ids)
    full(store, resumed)
    assert min(resumed.page_calls) == 5  # no walk back: the resume page holds seen movies
    assert set(ids) <= detailed_ids(store)
