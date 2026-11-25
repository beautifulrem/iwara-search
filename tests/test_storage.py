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
    assert rankings.count("tags", q="alpha") == 1
    assert [row.name for row in rankings.top("tags", limit=5, q="ALPHA", sort="movies")] == ["Tag Alpha"]
    assert [row.name for row in rankings.top("authors", limit=5, sort="views")] == [
        "Author Eleven",
        "Author Twelve",
    ]
    top = rankings.top_movies_by_author([11, 12], per_author=1)
    assert [card.source_site_id for card in top[11]] == [200]
    workbench = rankings.facet_workbench(limit=2)
    assert set(workbench) == {"characters", "tags", "authors", "origins"}

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


def test_fts_consistency_on_missing_and_entity_rename(store: CrawlStore) -> None:
    seed(
        store,
        (
            make_detail(
                10,
                title="First Stage",
                author=(7, "OldCreator"),
                tags=[(50, "OldTagName"), (51, "水着")],
                characters=[(60, "OldChar")],
                origins=[(70, "OldOrigin")],
            ),
            make_detail(
                11,
                title="Second Stage",
                author=(7, "OldCreator"),
                tags=[(50, "OldTagName")],
                characters=[(60, "OldChar")],
                origins=[(70, "OldOrigin")],
            ),
        ),
    )
    search = SearchStore(store.conn)
    assert sorted(ids(search, q="OldCreator")) == [10, 11]

    # Marking movie 11 missing removes its FTS rows immediately, and restoring re-adds them.
    store.mark_movie_missing(11, "https://oreno3d.com/movies/11")
    fts_rows = [
        r[0]
        for r in store.conn.execute(
            "SELECT rowid FROM movie_search WHERE movie_search MATCH '\"Second Stage\"'"
        )
    ]
    short_rows = [
        r[0]
        for r in store.conn.execute(
            "SELECT rowid FROM movie_search_short WHERE movie_search_short MATCH '\"Second\"*'"
        )
    ]
    assert fts_rows == []
    assert short_rows == []
    assert RankingStore(store.conn).dataset_status().movie_count == 1

    # Upstream renames entities on a third movie -> movie 10's FTS keywords update immediately!
    store.apply_movie_detail(
        make_detail(
            12,
            title="Third Stage",
            author=(7, "RenamedCreator"),
            tags=[(50, "RenamedTag")],
            characters=[(60, "RenamedChar")],
            origins=[(70, "RenamedOrigin")],
        )
    )
    assert ids(search, q="OldCreator") == []
    assert sorted(ids(search, q="RenamedCreator")) == [10, 12]
    assert sorted(ids(search, q="RenamedTag")) == [10, 12]
    assert sorted(ids(search, q="RenamedChar")) == [10, 12]
    assert sorted(ids(search, q="RenamedOrigin")) == [10, 12]


def test_jst_hot_score_and_stale_cutoff(store: CrawlStore) -> None:
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    jst = ZoneInfo("Asia/Tokyo")
    now_utc = datetime.now(UTC)
    now_jst = now_utc.astimezone(jst)
    one_hour_ago_jst = (now_jst - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    eight_hours_ago_jst = (now_jst - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")

    seed(
        store,
        (
            make_detail(1, title="Fresh 1h", published_at=one_hour_ago_jst, views=1000, favorites=0),
            make_detail(2, title="Older 8h", published_at=eight_hours_ago_jst, views=1000, favorites=0),
        ),
    )
    scores = dict(store.conn.execute("SELECT source_site_id, hot_score FROM movies").fetchall())
    # 1h old in JST (~1000 / 7) must strictly outrank 8h old in JST (~1000 / 14)
    assert scores[1] > scores[2] * 1.5

    # Stale detail cutoff uses JST wall clock to compare against naive JST published_at
    store.conn.execute("UPDATE movies SET detail_fetched_at = '2020-01-01T00:00:00+00:00'")
    stale = store.stale_detail_ids(window_days=1, refresh_after_hours=1, limit=10, now=now_utc)
    assert sorted(stale) == [1, 2]


def test_nfkc_entity_autocomplete_and_resolution(store: CrawlStore) -> None:
    seed(store, (make_detail(1, title="Test", tags=[(1, "4K"), (2, "MMD"), (3, "ダンス")]),))
    search = SearchStore(store.conn)
    assert [e.name for e in search.autocomplete("tags", "４Ｋ")] == ["4K"]
    assert [e.name for e in search.autocomplete("tags", "ｍｍｄ")] == ["MMD"]
    assert [e.name for e in search.autocomplete("tags", "ﾀﾞﾝｽ")] == ["ダンス"]
    matched, unmatched = search.resolve_entity_names("tags", "４Ｋ，ＭＭＤ、ﾀﾞﾝｽ,UnknownTag")
    assert matched == [1, 2, 3]
    assert unmatched == ["UnknownTag"]


def test_missing_movie_keeps_related_movies_and_tags(store: CrawlStore) -> None:
    seed(
        store,
        (
            make_detail(1, title="Archived Original", author=(9, "StudioX"), tags=[(1, "4K"), (2, "MMD")]),
            make_detail(2, title="Active Sibling", author=(9, "StudioX"), tags=[(1, "4K"), (3, "60fps")]),
        ),
    )
    store.mark_movie_missing(1, "https://oreno3d.com/movies/1")
    store.refresh_derived()
    search = SearchStore(store.conn)
    detail = search.get_movie(1)
    assert detail is not None
    assert detail.status == "missing"
    related = search.related_movies(1)
    assert [card.source_site_id for card in related] == [2]
    assert {tag.name for tag in related[0].tags} == {"4K", "60fps"}


def test_suppress_and_unsuppress_survive_crawl_ops(store: CrawlStore) -> None:
    from search_iwara.models import MovieListItem

    seed(
        store,
        (
            make_detail(100, title="Disputed Work", author=(1, "Creator"), tags=[(1, "MMD")]),
            make_detail(101, title="Normal Work", author=(1, "Creator"), tags=[(1, "MMD")]),
        ),
    )
    search = SearchStore(store.conn)
    rankings = RankingStore(store.conn)

    assert store.suppress_movies([100, 999]) == 2  # 100 existing + 999 pre-emptive stub
    assert search.get_movie(100) is None
    assert ids(search, q="Disputed") == []
    assert rankings.dataset_status().movie_count == 1

    # Subsequent crawl list/detail/missing calls must NOT resurrect suppressed items
    res = store.upsert_movie_list_item(
        MovieListItem(
            source_site_id=100,
            oreno3d_url="https://oreno3d.com/movies/100",
            title="Disputed Work Updated",
            author_name="Creator",
            thumbnail_url=None,
            view_count=999,
            favorite_count=99,
        )
    )
    assert res.needs_detail is False
    assert res.list_changed is False
    store.apply_movie_detail(make_detail(100, title="Disputed Work Resurrected"))
    store.mark_movie_missing(100, "https://oreno3d.com/movies/100")
    assert search.get_movie(100) is None
    assert ids(search, q="Disputed") == []

    # Unsuppress restores metadata-bearing 100 and drops empty stub 999
    assert store.unsuppress_movies([100, 999]) == 2
    assert search.get_movie(100) is not None
    assert ids(search, q="Disputed") == [100]
    assert store.conn.execute("SELECT 1 FROM movies WHERE source_site_id = 999").fetchone() is None
    store.reindex_all(verify=True)


def test_dynamic_facet_counts_and_v4_to_v5_upgrade(tmp_path: Path) -> None:
    from search_iwara.storage.migrations import MIGRATIONS

    path = tmp_path / "v4.sqlite3"
    conn = connect(path)
    # Build v1..v4 manually with legacy uncompacted FTS DDL and a 'missing' ghost row in FTS
    for idx, fn in enumerate(MIGRATIONS[:4], start=1):
        conn.execute("BEGIN IMMEDIATE")
        fn(conn)
        conn.execute(f"PRAGMA user_version = {idx}")
        conn.execute("COMMIT")
    conn.execute("DROP TABLE movie_search")
    conn.execute("CREATE VIRTUAL TABLE movie_search USING fts5(title, keywords, tokenize='trigram')")
    conn.execute(
        "INSERT INTO movies (id, source_site_id, oreno3d_url, title, status) "
        "VALUES (1, 1, 'https://oreno3d.com/movies/1', 'Active Gem', 'active'), "
        "       (2, 2, 'https://oreno3d.com/movies/2', 'Missing Ghost', 'missing')"
    )
    conn.execute(
        "INSERT INTO movie_search(rowid, title, keywords) VALUES (1, 'Active Gem', ''), (2, 'Missing Ghost', '')"
    )

    # Migrate v4 -> v5
    assert migrate(conn) == 1
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert int(conn.execute("SELECT value FROM app_meta WHERE key = 'active_movies'").fetchone()[0]) == 1
    ghost = conn.execute("SELECT rowid FROM movie_search WHERE movie_search MATCH '\"Missing\"'").fetchall()
    assert ghost == []

    store = CrawlStore(conn)
    store.apply_movie_detail(
        make_detail(3, title="Active Gem Encore", author=(5, "Kuro"), tags=[(10, "4K"), (11, "60fps")])
    )
    store.refresh_derived()
    search = SearchStore(conn)
    facets, sampled = search.facet_counts(SearchFilters(q="Encore"), limit=5, pinned={"tags": [11]})
    assert sampled is False
    assert [row.name for row in facets["tags"]][:2] == ["60fps", "4K"]
    assert facets["authors"][0].name == "Kuro"
    conn.close()


def test_mega_entity_rename_defers_fts_rebuild_to_refresh_derived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import search_iwara.storage.crawl_store as cs_mod

    monkeypatch.setattr(cs_mod, "INLINE_REINDEX_CAP", 1)
    store = CrawlStore.open(tmp_path / "mega.sqlite3")
    with store.transaction():
        for sid in (10, 11, 12):
            store.apply_movie_detail(make_detail(sid, title=f"Work {sid}", tags=[(99, "OldMegaTag")]))
    with store.transaction():
        store.apply_movie_detail(make_detail(13, title="Work 13", tags=[(99, "NewMegaTag")]))
    dirty = store.conn.execute("SELECT value FROM app_meta WHERE key = 'fts_dirty'").fetchone()
    assert dirty is not None
    assert dirty[0] == "1"
    store.refresh_derived(full=False)
    assert store.conn.execute("SELECT value FROM app_meta WHERE key = 'fts_dirty'").fetchone() is None
    assert (
        SearchStore(store.conn)
        .search(SearchFilters(q="NewMegaTag"), page=1, page_size=36, max_results=10_000)
        .total
        == 4
    )
    store.close()


def test_mixed_cjk_ascii_2char_queries_disjunctive_facets_and_inode_pool(tmp_path: Path) -> None:
    from search_iwara.storage.connection import ReadOnlyPool, StorageError

    db_file = tmp_path / "mixed.sqlite3"
    store = CrawlStore.open(db_file)
    seed(
        store,
        (
            make_detail(10, title="M字開脚 第1話 ドMな彼女", author=(1, "Alpha"), tags=[(1, "I字バランス")]),
            make_detail(11, title="Pure Dance Stage", author=(2, "Beta"), tags=[(2, "60fps")]),
        ),
    )
    # Mark unknown 404 stub 888 and metadata-bearing 11 as missing, then suppress & unsuppress
    store.mark_movie_missing(888, "https://oreno3d.com/movies/888")
    store.mark_movie_missing(11, "https://oreno3d.com/movies/11")
    store.suppress_movies([888, 11], reason="audit")
    assert store.unsuppress_movies([888, 11]) == 2
    assert store.conn.execute("SELECT 1 FROM movies WHERE source_site_id = 888").fetchone() is None
    assert (
        store.conn.execute("SELECT status FROM movies WHERE source_site_id = 11").fetchone()[0] == "missing"
    )

    # Restore 11 as active so both authors exist
    store.apply_movie_detail(
        make_detail(11, title="Pure Dance Stage", author=(2, "Beta"), tags=[(2, "60fps")])
    )
    store.refresh_derived(full=True)

    search = SearchStore(store.conn)
    for token in ("M字", "I字", "ドM", "Mな", "第1", "1話"):
        assert ids(search, q=token) == [10], token

    # Disjunctive ANY facet on author_any=[1] keeps sibling Author 2 ("Beta") selectable
    facets, _ = search.facet_counts(SearchFilters(author_any=[1]), limit=5, pinned={"authors": [1]})
    assert {r.name for r in facets["authors"]} == {"Alpha", "Beta"}
    store.close()

    # ReadOnlyPool detects atomic file replacement and unlink
    pool = ReadOnlyPool(db_file)
    try:
        assert pool.get().execute("SELECT COUNT(*) FROM movies").fetchone()[0] == 2
        replacement = tmp_path / "replacement.sqlite3"
        other = CrawlStore.open(replacement)
        seed(other, (make_detail(99, title="Replaced DB"),))
        other.close()
        for suffix in ("-wal", "-shm"):
            wal = db_file.with_name(db_file.name + suffix)
            wal.unlink(missing_ok=True)
        replacement.replace(db_file)
        assert pool.get().execute("SELECT source_site_id FROM movies").fetchone()[0] == 99
        db_file.unlink()
        with pytest.raises(StorageError):
            pool.get()
    finally:
        pool.close()
