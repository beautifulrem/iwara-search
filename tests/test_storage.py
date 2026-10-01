from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from search_iwara.models import MovieListItem, SearchFilters
from search_iwara.storage import SCHEMA_VERSION, CrawlStore, RankingStore, SearchStore, connect, migrate
from tests.factories import make_detail, seed

BOOLEAN_FIXTURE = (
    make_detail(
        101,
        title="amber night dance",
        author=(10, "Author A"),
        tags=[(1, "Tag One"), (2, "Tag Two")],
        origins=[(11, "Origin A")],
        characters=[(21, "Character A")],
    ),
    make_detail(
        102,
        title="amber dawn",
        author=(20, "Author B"),
        tags=[(2, "Tag Two"), (3, "Tag Three")],
        origins=[(12, "Origin B")],
        characters=[(22, "Character B")],
        published_at="2026-04-10 05:12",
    ),
    make_detail(
        103,
        title="moonlight parade",
        author=(10, "Author A"),
        tags=[(3, "Tag Three")],
        origins=[(11, "Origin A")],
        characters=[(23, "Character C")],
        published_at="2026-04-09 05:12",
    ),
)


@pytest.fixture
def search(store: CrawlStore) -> SearchStore:
    seed(store, BOOLEAN_FIXTURE)
    return SearchStore(store.conn)


def ids(search: SearchStore, **kwargs: object) -> list[int]:
    result = search.search(SearchFilters(**kwargs), page=1, page_size=20, max_results=10_000)  # type: ignore[arg-type]
    return [card.source_site_id for card in result.items]


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"q": "amber night", "title_mode": "all"}, [101]),
        ({"q": "amber night", "title_mode": "any"}, [101, 102]),
        ({"author_any": [10]}, [101, 103]),
        ({"author_not": [10]}, [102]),
        ({"tag_all": [2, 3]}, [102]),
        ({"tag_any": [1, 3]}, [101, 102, 103]),
        ({"tag_not": [1]}, [102, 103]),
        ({"q": "amber", "author_any": [20], "tag_not": [1]}, [102]),
        ({"origin_any": [11]}, [101, 103]),
        ({"origin_not": [11]}, [102]),
        ({"character_any": [22]}, [102]),
        ({"character_not": [21]}, [102, 103]),
        ({"published_from": "2026-04-10", "published_to": "2026-04-11"}, [101, 102]),
        ({"published_to": "2026-04-09"}, [103]),
        ({"min_views": 1020, "max_views": 1030, "min_favorites": 102, "max_favorites": 103}, [102, 103]),
        ({"sort": "published_asc"}, [103, 102, 101]),
        ({"sort": "views_desc"}, [103, 102, 101]),
        ({"sort": "favorites_asc"}, [101, 102, 103]),
        ({"sort": "popularity_desc"}, [103, 102, 101]),
    ],
)
def test_boolean_search(search: SearchStore, filters: dict[str, object], expected: list[int]):
    assert ids(search, **filters) == expected


def test_search_matches_names_not_just_titles(search: SearchStore):
    assert ids(search, q="Three") == [102, 103]  # tag name only
    assert ids(search, q="moonlight Three") == [103]  # title AND tag
    assert ids(search, q="parade Character") == [103]  # title AND character name
    assert ids(search, q="Origin", title_mode="any") == [101, 102, 103]


def test_cjk_substring_search(store: CrawlStore):
    title = "【MMD】潜入!射精我慢賭博!~キヴォトスのピンク色の闇を暴け!~"
    seed(store, (make_detail(201, title=title, author=(30, "Author C"), tags=[(4, "Tag Four")]),))
    search = SearchStore(store.conn)
    assert search.trigram
    assert ids(search, q="キヴォトス") == [201]  # trigram FTS
    assert ids(search, q="我慢") == [201]  # 2 chars -> LIKE fallback
    assert ids(search, q="【MMD】潜入！射精我慢賭博！～キヴォトスのピンク色の闇を暴け！～") == [201]  # NFKC
    assert ids(search, q="MMD キヴォトス") == [201]
    assert ids(search, q='"quoted" 100%') == []  # FTS/LIKE metacharacters are escaped


def test_result_window_is_capped(store: CrawlStore):
    seed(store, tuple(make_detail(i, title=f"movie {i}") for i in range(1, 31)))
    result = SearchStore(store.conn).search(SearchFilters(), page=99, page_size=10, max_results=25)
    assert result.total == 25
    assert result.total_is_capped
    assert result.page == 3  # clamped to the last page
    assert result.page_count == 3


def test_detail_replaces_relations_without_duplicates(store: CrawlStore):
    seed(store, (make_detail(101, title="alpha", tags=[(1, "Tag One"), (2, "Tag Two")]),))
    seed(store, (make_detail(101, title="alpha updated", tags=[(2, "Tag Two")]),))
    movie = SearchStore(store.conn).get_movie(101)
    assert movie is not None
    assert movie.card.title == "alpha updated"
    assert [tag.id for tag in movie.tags] == [2]
    assert ids(SearchStore(store.conn), q="alpha updated") == [101]
    assert SearchStore(store.conn).get_movie(999) is None


def test_related_movies_are_weighted(store: CrawlStore):
    seed(
        store,
        (
            make_detail(
                101,
                title="A",
                author=(10, "Author A"),
                tags=[(1, "dance"), (2, "voice")],
                origins=[(11, "Genshin")],
                characters=[(21, "Amber")],
            ),
            make_detail(
                102,
                title="B",
                author=(10, "Author A"),
                tags=[(1, "dance"), (3, "mmd")],
                origins=[(12, "Vocaloid")],
                characters=[(21, "Amber"), (22, "Lumine")],
            ),  # 10+5+1
            make_detail(
                103,
                title="C",
                author=(20, "Author B"),
                tags=[(2, "voice"), (4, "r18")],
                origins=[(11, "Genshin")],
                characters=[(23, "Lisa")],
            ),  # 5+1
            make_detail(
                104,
                title="D",
                author=(30, "Author C"),
                tags=[(5, "solo")],
                origins=[(13, "Honkai")],
                characters=[(24, "Bronya")],
            ),  # 0
        ),
    )
    related = SearchStore(store.conn).related_movies(101)
    assert [card.source_site_id for card in related] == [102, 103]
    assert related[0].author_name == "Author A"


def test_list_upsert_tracks_new_and_changed(store: CrawlStore):
    item = MovieListItem(500, "https://oreno3d.com/movies/500", "fresh", "Someone", None, 1, 0)
    with store.transaction():
        first = store.upsert_movie_list_item(item)
        same = store.upsert_movie_list_item(item)
        changed = store.upsert_movie_list_item(
            MovieListItem(500, "https://oreno3d.com/movies/500", "fresh", "Someone", None, 5, 0)
        )
    assert (first.is_new, first.needs_detail) == (True, True)
    assert (same.is_new, same.list_changed, same.needs_detail) == (False, False, True)
    assert changed.list_changed
    assert ids(SearchStore(store.conn), q="Someone") == [500]  # list-only rows are searchable too


def test_missing_movies_are_hidden(store: CrawlStore):
    seed(store, (make_detail(101, title="gone soon"),))
    with store.transaction():
        store.mark_movie_missing(101, "https://oreno3d.com/movies/101")
    assert ids(SearchStore(store.conn)) == []
    movie = SearchStore(store.conn).get_movie(101)
    assert movie is not None
    assert movie.status == "missing"


def test_error_backoff_and_cap(store: CrawlStore):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    error = RuntimeError("boom")
    with store.transaction():
        for _ in range(3):
            store.log_error(
                entity_type="movie", entity_id="7", operation="detail", url="u", error=error, now=now
            )
    row = store.conn.execute("SELECT attempts, next_retry_at, error_type FROM crawl_errors").fetchone()
    assert row["attempts"] == 3
    assert row["error_type"] == "RuntimeError"
    assert row["next_retry_at"] == (now + timedelta(hours=2)).isoformat()  # 30min * 2^2
    assert store.retryable_failed_movie_ids(max_attempts=6, now=now) == []  # not due yet
    assert store.retryable_failed_movie_ids(max_attempts=6, now=now + timedelta(hours=3)) == [7]
    assert store.retryable_failed_movie_ids(max_attempts=3, now=now + timedelta(days=30)) == []  # capped
    with store.transaction():
        store.clear_error(entity_type="movie", entity_id="7", operation="detail")
    assert store.conn.execute("SELECT COUNT(*) FROM crawl_errors").fetchone()[0] == 0


def test_stale_detail_selection(store: CrawlStore):
    seed(
        store,
        (
            make_detail(1, title="recent", published_at="2026-09-25 10:00"),
            make_detail(2, title="old", published_at="2020-01-01 10:00"),
        ),
    )
    store.conn.execute("UPDATE movies SET detail_fetched_at = '2026-09-01T00:00:00+00:00'")
    now = datetime(2026, 10, 1, tzinfo=UTC)
    assert store.stale_detail_ids(window_days=30, refresh_after_hours=72, limit=10, now=now) == [1]
    assert store.stale_detail_ids(window_days=30, refresh_after_hours=72, limit=0, now=now) == []


def test_state_and_missing_detail_queue(store: CrawlStore):
    with store.transaction():
        store.set_state("k", 5)
        store.set_state("bad", "x")
        store.upsert_movie_list_item(
            MovieListItem(9, "https://oreno3d.com/movies/9", "t", None, None, None, None)
        )
    assert store.get_state_int("k") == 5
    assert store.get_state_int("bad", 3) == 3
    assert store.get_state_int("missing", 7) == 7
    assert store.movies_missing_detail() == [9]


def test_transactions_roll_back_and_nest(store: CrawlStore):
    def failing_unit_of_work() -> None:
        with store.transaction():
            store.set_state("k", 1)
            with store.transaction():
                store.set_state("j", 2)
            raise RuntimeError

    with pytest.raises(RuntimeError):
        failing_unit_of_work()
    assert store.get_state_int("k") == 0
    assert store.get_state_int("j") == 0


def test_rankings_and_autocomplete(seeded: CrawlStore):
    rankings = RankingStore(seeded.conn)
    authors = rankings.top("authors", limit=10)
    assert [row.name for row in authors] == ["Author Eleven", "Author Twelve"]
    assert authors[0].movie_count == 2
    assert rankings.count("categories") == 4
    categories = rankings.top("categories", limit=2, offset=1)
    assert len(categories) == 2
    assert {row.kind for row in rankings.top("categories", limit=10)} == {"tags", "origins"}
    top = rankings.top_movies_by_author([11, 12], per_author=1)
    assert [card.source_site_id for card in top[11]] == [200]
    sidebar = rankings.sidebar(limit=1)
    assert set(sidebar) == {"characters", "authors", "categories"}

    search = SearchStore(seeded.conn)
    assert [item.name for item in search.autocomplete("authors", "eleven")] == ["Author Eleven"]
    assert [item.name for item in search.autocomplete("tags", "")][:1] == ["Tag Alpha"]  # most popular first
    assert search.autocomplete("tags", "%") == []  # LIKE wildcards are literal
    assert [item.id for item in search.resolve_entities("tags", [32, 999, 31])] == [32, 31]
    assert search.resolve_entities("tags", []) == []


def test_dataset_status_and_runs(store: CrawlStore):
    rankings = RankingStore(store.conn)
    assert rankings.dataset_status().last_success_at is None
    run = store.start_run("latest")
    store.finish_run(run, status="success", counters={"pages_checked": 2, "bogus": 1})
    status = rankings.dataset_status()
    assert status.last_run_status == "success"
    assert status.last_success_at is not None
    row = store.conn.execute("SELECT pages_checked FROM sync_runs").fetchone()
    assert row[0] == 2


def test_migrate_is_idempotent(db_path: Path):
    connection = connect(db_path)
    assert migrate(connection) == SCHEMA_VERSION
    assert migrate(connection) == 0
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="newer"):
        migrate(connection)
    connection.close()


def test_migrates_legacy_database_and_sanitises_urls(tmp_path: Path):
    """A 0.1.x database (no user_version, title-only FTS, unsafe URL) upgrades in place."""

    path = tmp_path / "legacy.sqlite3"
    legacy = sqlite3.connect(path)
    legacy.executescript(
        """
        CREATE TABLE authors (id INTEGER PRIMARY KEY AUTOINCREMENT, source_site_id INTEGER NOT NULL UNIQUE,
            name TEXT NOT NULL, oreno3d_url TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE movies (id INTEGER PRIMARY KEY AUTOINCREMENT, source_site_id INTEGER NOT NULL UNIQUE,
            oreno3d_url TEXT NOT NULL, external_video_url TEXT, title TEXT NOT NULL DEFAULT '',
            author_id INTEGER, author_display_name TEXT, thumbnail_url TEXT, published_at TEXT,
            view_count INTEGER, favorite_count INTEGER, author_comment TEXT, status TEXT NOT NULL DEFAULT 'active',
            list_seen_at TEXT, detail_fetched_at TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE crawl_errors (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL, operation TEXT NOT NULL, url TEXT NOT NULL, error_message TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 1, last_failed_at TEXT NOT NULL,
            UNIQUE(entity_type, entity_id, operation));
        CREATE INDEX idx_movies_status ON movies(status);
        CREATE VIRTUAL TABLE movie_fts USING fts5(title, content='movies', content_rowid='id');
        CREATE TRIGGER movies_ai AFTER INSERT ON movies BEGIN
            INSERT INTO movie_fts(rowid, title) VALUES (new.id, new.title);
        END;
        INSERT INTO authors (source_site_id, name) VALUES (5, 'Legacy Author');
        INSERT INTO movies (source_site_id, oreno3d_url, external_video_url, title, author_id, view_count,
                            author_comment)
        VALUES (1, 'https://oreno3d.com/movies/1', 'javascript:alert(1)//iwara', 'ダンス練習動画', 1, 10,
                'first\\nsecond it\\''s');
        """
    )
    legacy.close()

    store = CrawlStore.open(path)
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert store.conn.execute("SELECT external_video_url FROM movies").fetchone()[0] is None
    assert store.conn.execute("SELECT author_comment FROM movies").fetchone()[0] == "first\nsecond it's"
    search = SearchStore(store.conn)
    assert ids(search, q="練習動画") == [1]
    assert ids(search, q="練習") == [1]  # 2-char CJK token served by the n-gram index
    assert ids(search, q="Legacy Author") == [1]
    assert [row.name for row in RankingStore(store.conn).top("authors", limit=5)] == ["Legacy Author"]
    store.close()


def test_readonly_connection_rejects_writes_and_missing_db(seeded: CrawlStore, db_path: Path, tmp_path: Path):
    readonly = connect(db_path, readonly=True)
    with pytest.raises(sqlite3.OperationalError):
        readonly.execute("DELETE FROM movies")
    readonly.close()
    from search_iwara.storage import StorageError

    with pytest.raises(StorageError):
        connect(tmp_path / "nope.sqlite3", readonly=True)


def test_short_tokens_are_served_by_the_short_index(store: CrawlStore):
    seed(
        store,
        (
            make_detail(1, title="MMD summer 夏祭り", tags=[(1, "3D")]),
            make_detail(2, title="plain summer walk", tags=[(2, "misc")]),
        ),
    )
    search = SearchStore(store.conn)
    assert ids(search, q="mm") == [1]  # word prefix ("MMD"), not the substring in "summer"
    assert ids(search, q="3d") == [1]  # tag names are indexed too
    assert ids(search, q="夏") == [1]  # CJK unigram
    assert ids(search, q="祭り") == [1]  # CJK bigram
    assert ids(search, q="mm walk", title_mode="any") == [2, 1]
    plan = " ".join(
        str(row[3])
        for row in store.conn.execute(
            "EXPLAIN QUERY PLAN SELECT rowid FROM movie_search_short WHERE movie_search_short MATCH ?",
            ('"mm"*',),
        )
    )
    assert "VIRTUAL TABLE INDEX" in plan
