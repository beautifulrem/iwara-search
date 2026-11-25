"""Latency budgets on a production-sized synthetic database (200k movies, ~1M tag links).

Run with ``pytest -m slow``. The database is built through the real upgrade path: the v1
baseline schema is bulk-loaded, then ``migrate`` builds the FTS index, scores and read models.
Budgets are generous multiples of what a laptop measures, so they catch algorithmic
regressions (full scans, N+1s) rather than machine noise.
"""

from __future__ import annotations

import random
import sqlite3
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from search_iwara.models import SearchFilters
from search_iwara.storage import CrawlStore, RankingStore, SearchStore, connect, migrate
from search_iwara.storage.migrations import MIGRATIONS

pytestmark = pytest.mark.slow

MOVIES = 200_000
WORDS = [
    "yelan",
    "dance",
    "mmd",
    "genshin",
    "honkai",
    "blue",
    "archive",
    "remake",
    "short",
    "loop",
    "night",
    "summer",
    "school",
    "idol",
    "live",
    "stage",
    "ダンス",
    "キヴォトス",
    "水着",
    "初音",
    "原神",
    "崩坏",
    "舞蹈",
    "练习",
    "演唱会",
    "夏日",
]


def _build(path: Path) -> None:
    rng = random.Random(42)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("BEGIN")
    MIGRATIONS[0](conn)
    conn.execute("PRAGMA user_version = 1")
    for table, count in (("authors", 5_000), ("tags", 2_000), ("origins", 500), ("characters", 3_000)):
        conn.executemany(
            f"INSERT INTO {table} (id, source_site_id, name) VALUES (?, ?, ?)",
            ((i, i, f"{table[:-1]} {i} {rng.choice(WORDS)}") for i in range(1, count + 1)),
        )
    conn.executemany(
        """
        INSERT INTO movies (id, source_site_id, oreno3d_url, title, author_id, published_at, view_count,
                            favorite_count, status, detail_fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', '2026-01-01T00:00:00+00:00')
        """,
        (
            (
                i,
                i,
                f"https://oreno3d.com/movies/{i}",
                " ".join(rng.choices(WORDS, k=4)) + f" #{i}",
                rng.randint(1, 5_000),
                f"20{rng.randint(18, 26)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d} 12:00",
                int(rng.paretovariate(1.2) * 100),
                int(rng.paretovariate(1.3) * 5),
            )
            for i in range(1, MOVIES + 1)
        ),
    )
    for table, column, span, per_movie in (
        ("movie_tags", "tag_id", 2_000, 5),
        ("movie_characters", "character_id", 3_000, 1),
        ("movie_origins", "origin_id", 500, 1),
    ):
        conn.executemany(
            f"INSERT OR IGNORE INTO {table} (movie_id, {column}) VALUES (?, ?)",
            (
                (movie, min(span, int(rng.paretovariate(0.8))))
                for movie in range(1, MOVIES + 1)
                for _ in range(per_movie)
            ),
        )
    conn.execute("COMMIT")
    conn.close()


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    path = tmp_path_factory.mktemp("perf") / "perf.sqlite3"
    _build(path)
    writer = connect(path)
    started = time.perf_counter()
    migrate(writer)  # v1 -> current: FTS build, scores, entity_stats
    migration_seconds = time.perf_counter() - started
    writer.close()
    assert migration_seconds < 180, f"upgrade migration took {migration_seconds:.1f}s"
    readonly = connect(path, readonly=True)
    yield readonly
    readonly.close()


def timed(action: Callable[[], object], repeat: int = 9) -> tuple[float, float]:
    """Return (p50_ms, p95_ms) after one warmup run instead of cherry-picking min()."""

    action()  # warm the page cache like a running server would
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        action()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    p50 = samples[len(samples) // 2]
    p95 = samples[min(len(samples) - 1, round(0.95 * (len(samples) - 1)))]
    return p50, p95


def search(db: sqlite3.Connection, page: int = 1, **filters: object) -> Callable[[], object]:
    store = SearchStore(db)
    return lambda: store.search(SearchFilters(**filters), page=page, page_size=36, max_results=10_000)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("label", "filters", "budget_ms"),
    [
        ("default latest", {}, 40),
        ("hot", {"sort": "hot_desc"}, 40),
        ("popularity", {"sort": "popularity_desc"}, 40),
        ("favorites asc", {"sort": "favorites_asc"}, 40),
        ("views", {"sort": "views_desc"}, 40),
        ("fts latin", {"q": "yelan dance"}, 250),
        ("fts cjk", {"q": "キヴォトス"}, 250),
        ("2-char cjk (n-gram index)", {"q": "水着"}, 150),
        ("1-char cjk (n-gram index)", {"q": "夏"}, 150),
        ("mixed any", {"q": "初音 dance", "title_mode": "any"}, 300),
        ("2-letter latin (prefix index)", {"q": "mm"}, 150),
        ("tag any", {"tag_any": [1, 2]}, 250),
        ("tag all + not", {"tag_all": [1, 3], "tag_not": [2]}, 120),
        ("author", {"author_any": [7]}, 60),
        ("date range + views", {"published_from": "2025-01-01", "min_views": 500}, 250),
    ],
)
def test_search_budgets(
    db: sqlite3.Connection, label: str, filters: dict[str, object], budget_ms: float
) -> None:
    p50, p95 = timed(search(db, **filters))
    assert p50 < budget_ms, f"{label} P50: {p50:.1f}ms > {budget_ms}ms"
    assert p95 < budget_ms * 1.8, f"{label} P95: {p95:.1f}ms > {budget_ms * 1.8:.1f}ms"


def test_deepest_page_is_bounded(db: sqlite3.Connection) -> None:
    p50, _ = timed(search(db, page=10_000 // 36))
    assert p50 < 100, f"deep page {p50:.1f}ms"


def test_workbench_and_rankings(db: sqlite3.Connection) -> None:
    rankings = RankingStore(db)
    store = SearchStore(db)
    assert timed(lambda: rankings.facet_workbench(limit=5))[0] < 25
    assert timed(lambda: store.facet_counts(SearchFilters(q="yelan"), limit=5))[0] < 150
    assert timed(lambda: rankings.top("categories", limit=60, offset=600))[0] < 30
    assert timed(lambda: rankings.top("tags", limit=60, q="dan", sort="hot"))[0] < 30
    assert timed(lambda: rankings.count("categories"))[0] < 30
    # Full 60-author /authors page budget (was 134-270ms before idx_movies_author_top!)
    assert timed(lambda: rankings.top_movies_by_author(list(range(1, 61)), per_author=8))[0] < 80
    assert timed(rankings.dataset_status)[0] < 15


def test_related_and_detail(db: sqlite3.Connection) -> None:
    store = SearchStore(db)
    assert timed(lambda: store.get_movie(123_456))[0] < 20
    assert timed(lambda: store.related_movies(123_456))[0] < 40


def test_autocomplete(db: sqlite3.Connection) -> None:
    store = SearchStore(db)
    assert timed(lambda: store.autocomplete("tags", "dan"))[0] < 50
    assert timed(lambda: store.autocomplete("authors", ""))[0] < 20


def test_refresh_derived_after_sync(db: sqlite3.Connection, tmp_path: Path) -> None:
    path = Path(db.execute("PRAGMA database_list").fetchone()[2])
    store = CrawlStore(connect(path))
    try:
        started = time.perf_counter()
        store.refresh_derived()
        assert time.perf_counter() - started < 30
    finally:
        store.close()
