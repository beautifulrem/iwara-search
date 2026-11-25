"""Reproducible 200,000-movie benchmark harness for Search Iwara.

Measures on a deterministic 200,000-movie synthetic database (~1M tag links):
1. Migration & FTS build wall time + peak RSS + on-disk table/index sizes (dbstat / file size)
2. EXPLAIN QUERY PLAN verification for core query shapes
3. Storage-layer query latencies (Cold first-run + Warm P50 / P95 / P99 over N=60 runs)
4. End-to-end HTTP + Jinja + GZip latencies via ASGI TestClient (P50 / P95 / P99 over N=40 runs)
5. Concurrent read throughput & tail latency (16 reader threads) + mixed reader/writer commits
6. Derived-data refresh (full & incremental) and online backup + quick_check latency
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import resource
import sqlite3
import statistics
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from search_iwara.config import get_settings
from search_iwara.models import EntityRef, MovieDetail, SearchFilters
from search_iwara.storage import CrawlStore, RankingStore, ReadOnlyPool, SearchStore, connect, migrate
from search_iwara.storage.migrations import MIGRATIONS
from search_iwara.storage.sql import SORT_CLAUSES
from search_iwara.web import create_app

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


def build_v1_dataset(path: Path) -> float:
    t0 = time.perf_counter()
    rng = random.Random(42)  # noqa: S311 - deterministic benchmark seed
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
    return time.perf_counter() - t0


def percentiles(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)
    count = len(ordered)

    def pct(p: float) -> float:
        idx = min(count - 1, max(0, round((p / 100.0) * (count - 1))))
        return round(ordered[idx], 3)

    return {
        "min_ms": round(ordered[0], 3),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": pct(95),
        "p99_ms": pct(99),
        "max_ms": round(ordered[-1], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
    }


def measure_op(
    db_path: Path, fn_factory: Callable[[sqlite3.Connection], Callable[[], Any]], runs: int = 60
) -> dict[str, Any]:
    cold_conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    cold_conn.row_factory = sqlite3.Row
    cold_conn.execute("PRAGMA query_only = ON")
    cold_conn.execute("PRAGMA cache_size = -2000")
    cold_fn = fn_factory(cold_conn)
    t0 = time.perf_counter()
    cold_fn()
    cold_ms = round((time.perf_counter() - t0) * 1000, 3)
    cold_conn.close()

    warm_conn = connect(db_path, readonly=True)
    warm_fn = fn_factory(warm_conn)
    warm_fn()
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        warm_fn()
        samples.append((time.perf_counter() - t0) * 1000)
    warm_conn.close()
    return {"cold_ms": cold_ms, **percentiles(samples)}


def collect_table_sizes(conn: sqlite3.Connection) -> dict[str, float]:
    try:
        rows = conn.execute(
            """
            SELECT name, ROUND(SUM(pgsize) / (1024.0 * 1024.0), 2) AS mb
            FROM dbstat
            GROUP BY name
            ORDER BY mb DESC
            LIMIT 20
            """
        ).fetchall()
        return {str(r[0]): float(r[1]) for r in rows}
    except sqlite3.OperationalError:
        return {}


def _collect_query_plans(db_path: Path) -> dict[str, list[str]]:
    ro = connect(db_path, readonly=True)
    plans: dict[str, list[str]] = {}
    store_for_plan = SearchStore(ro)
    plan_cases = {
        "default_latest": SearchFilters(),
        "hot_desc": SearchFilters(sort="hot_desc"),
        "fts_trigram": SearchFilters(q="yelan dance"),
        "fts_short_cjk": SearchFilters(q="水着"),
        "fts_mixed_all": SearchFilters(q="yelan 水着", title_mode="all"),
        "tag_all_and_not": SearchFilters(tag_all=[1, 3], tag_not=[2]),
        "author_any": SearchFilters(author_any=[7]),
        "date_and_views": SearchFilters(published_from="2025-01-01", min_views=500),
    }
    for name, flt in plan_cases.items():
        where_sql, params = store_for_plan.build_where(flt)
        order_sql = SORT_CLAUSES[flt.sort]
        sql = f"EXPLAIN QUERY PLAN SELECT m.id FROM movies m WHERE {where_sql} ORDER BY {order_sql} LIMIT 36"
        eqp = ro.execute(sql, params).fetchall()
        plans[name] = [str(r[3]) for r in eqp]
    ro.close()
    return plans


def _measure_storage_queries(db_path: Path) -> dict[str, Any]:
    queries: dict[str, Callable[[sqlite3.Connection], Callable[[], Any]]] = {
        "search_default_latest": lambda c: (
            lambda: SearchStore(c).search(SearchFilters(), page=1, page_size=36, max_results=10_000)
        ),
        "search_hot_desc": lambda c: (
            lambda: SearchStore(c).search(
                SearchFilters(sort="hot_desc"), page=1, page_size=36, max_results=10_000
            )
        ),
        "search_deep_page_277": lambda c: (
            lambda: SearchStore(c).search(SearchFilters(), page=277, page_size=36, max_results=10_000)
        ),
        "search_fts_latin": lambda c: (
            lambda: SearchStore(c).search(
                SearchFilters(q="yelan dance"), page=1, page_size=36, max_results=10_000
            )
        ),
        "search_fts_cjk_trigram": lambda c: (
            lambda: SearchStore(c).search(
                SearchFilters(q="キヴォトス"), page=1, page_size=36, max_results=10_000
            )
        ),
        "search_fts_cjk_2char": lambda c: (
            lambda: SearchStore(c).search(SearchFilters(q="水着"), page=1, page_size=36, max_results=10_000)
        ),
        "search_fts_cjk_1char": lambda c: (
            lambda: SearchStore(c).search(SearchFilters(q="夏"), page=1, page_size=36, max_results=10_000)
        ),
        "search_fts_mixed_all": lambda c: (
            lambda: SearchStore(c).search(
                SearchFilters(q="yelan 水着", title_mode="all"), page=1, page_size=36, max_results=10_000
            )
        ),
        "search_fts_mixed_any": lambda c: (
            lambda: SearchStore(c).search(
                SearchFilters(q="初音 dance", title_mode="any"), page=1, page_size=36, max_results=10_000
            )
        ),
        "search_tag_all_and_not": lambda c: (
            lambda: SearchStore(c).search(
                SearchFilters(tag_all=[1, 3], tag_not=[2]), page=1, page_size=36, max_results=10_000
            )
        ),
        "search_high_freq_tag_not": lambda c: (
            lambda: SearchStore(c).search(
                SearchFilters(tag_not=[1]), page=1, page_size=36, max_results=10_000
            )
        ),
        "search_date_and_views": lambda c: (
            lambda: SearchStore(c).search(
                SearchFilters(published_from="2025-01-01", min_views=500),
                page=1,
                page_size=36,
                max_results=10_000,
            )
        ),
        "detail_get_movie": lambda c: lambda: SearchStore(c).get_movie(123_456),
        "detail_related_movies": lambda c: lambda: SearchStore(c).related_movies(123_456),
        "rankings_facet_workbench": lambda c: lambda: RankingStore(c).facet_workbench(limit=5),
        "rankings_categories_p10": lambda c: lambda: RankingStore(c).top("categories", limit=60, offset=540),
        "rankings_authors_top_movies": lambda c: (
            lambda: RankingStore(c).top_movies_by_author([1, 2, 3, 4, 5], per_author=8)
        ),
        "rankings_dataset_status": lambda c: lambda: RankingStore(c).dataset_status(),
        "autocomplete_tags_prefix": lambda c: (
            lambda: SearchStore(c).autocomplete_with_counts("tags", "dan", limit=10)
        ),
    }
    return {name: measure_op(db_path, fn) for name, fn in queries.items()}


def _measure_http(db_path: Path) -> tuple[float, dict[str, Any]]:
    t_boot = time.perf_counter()
    app = create_app(get_settings(db_path=db_path))
    with TestClient(app) as client:
        boot_ms = round((time.perf_counter() - t_boot) * 1000, 3)
        http_routes = {
            "GET /": "/",
            "GET /?q=yelan+dance": "/?q=yelan+dance",
            "GET /?tag_all=1,3&tag_not=2": "/?tag_all=1,3&tag_not=2",
            "GET /movies/123456": "/movies/123456",
            "GET /authors": "/authors",
            "GET /categories": "/categories",
            "GET /api/tags?query=dan&counts=1": "/api/tags?query=dan&counts=1",
            "GET /readyz": "/readyz",
        }
        http_stats: dict[str, Any] = {}
        for label, url in http_routes.items():
            resp = client.get(url, headers={"accept-encoding": "gzip"})
            if resp.status_code != 200:
                raise RuntimeError(f"{label} returned {resp.status_code}")
            samples = []
            for _ in range(40):
                t0 = time.perf_counter()
                r = client.get(url, headers={"accept-encoding": "gzip"})
                if r.status_code != 200:
                    raise RuntimeError(f"{label} returned {r.status_code}")
                samples.append((time.perf_counter() - t0) * 1000)
            http_stats[label] = percentiles(samples)
    return boot_ms, http_stats


def _measure_concurrency(db_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    pool = ReadOnlyPool(db_path)
    urls_mix = [
        SearchFilters(),
        SearchFilters(q="yelan"),
        SearchFilters(q="水着"),
        SearchFilters(tag_all=[1, 3], tag_not=[2]),
        SearchFilters(sort="hot_desc"),
        SearchFilters(author_any=[7]),
    ]

    def reader_task(i: int) -> float:
        conn = pool.get()
        store = SearchStore(conn)
        t0 = time.perf_counter()
        store.search(urls_mix[i % len(urls_mix)], page=1, page_size=36, max_results=10_000)
        return (time.perf_counter() - t0) * 1000

    t_conc = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        read_samples = list(ex.map(reader_task, range(320)))
    conc_wall = time.perf_counter() - t_conc
    ro_stats = {
        "requests": 320,
        "qps": round(320 / conc_wall, 1),
        "errors": 0,
        **percentiles(read_samples),
    }

    stop_writer = threading.Event()
    writer_errors: list[str] = []

    def writer_loop() -> None:
        ws = CrawlStore(connect(db_path))
        try:
            for batch_idx in range(8):
                if stop_writer.is_set():
                    break
                with ws.transaction():
                    for j in range(25):
                        sid = 500_000 + batch_idx * 25 + j
                        ws.apply_movie_detail(
                            MovieDetail(
                                source_site_id=sid,
                                oreno3d_url=f"https://oreno3d.com/movies/{sid}",
                                title=f"concurrent write yelan 水着 #{sid}",
                                external_video_url=f"https://www.iwara.tv/video/{sid}",
                                author=EntityRef(1, "author 1 yelan"),
                                tags=[EntityRef(1, "tag 1 yelan"), EntityRef(2, "tag 2 dance")],
                                origins=[EntityRef(1, "origin 1")],
                                characters=[EntityRef(1, "character 1")],
                                thumbnail_url=None,
                                published_at="2026-11-25 12:00",
                                view_count=100,
                                favorite_count=10,
                                author_comment="test",
                            )
                        )
        except Exception as exc:
            writer_errors.append(str(exc))
        finally:
            ws.close()

    wt = threading.Thread(target=writer_loop)
    wt.start()
    rw_errors = 0
    rw_samples: list[float] = []
    t_rw = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        for fut in concurrent.futures.as_completed([ex.submit(reader_task, i) for i in range(320)]):
            try:
                rw_samples.append(fut.result())
            except Exception:
                rw_errors += 1
    stop_writer.set()
    wt.join()
    rw_wall = time.perf_counter() - t_rw
    pool.close()
    rw_stats = {
        "read_requests": 320,
        "write_movies_committed": 200,
        "read_qps": round(320 / rw_wall, 1),
        "read_errors": rw_errors,
        "writer_errors": writer_errors,
        **percentiles(rw_samples),
    }
    return ro_stats, rw_stats


def _measure_maintenance(db_path: Path, tmp_dir: Path) -> dict[str, Any]:
    cs = CrawlStore(connect(db_path))
    t0 = time.perf_counter()
    cs.refresh_derived(full=True)
    refresh_full_ms = round((time.perf_counter() - t0) * 1000, 2)
    t0 = time.perf_counter()
    cs.refresh_derived(full=False)
    refresh_inc_ms = round((time.perf_counter() - t0) * 1000, 2)
    cs.close()

    bkp_path = tmp_dir / "backup.sqlite3"
    t0 = time.perf_counter()
    src = connect(db_path, readonly=True)
    dst = sqlite3.connect(bkp_path)
    src.backup(dst, pages=4096)
    chk = dst.execute("PRAGMA quick_check").fetchone()[0]
    dst.close()
    src.close()
    backup_ms = round((time.perf_counter() - t0) * 1000, 2)

    peak_rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 2)
    return {
        "refresh_derived_full_ms": refresh_full_ms,
        "refresh_derived_incremental_ms": refresh_inc_ms,
        "online_backup_plus_quick_check_ms": backup_ms,
        "backup_integrity": chk,
        "peak_rss_mb": peak_rss_mb,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    results: dict[str, Any] = {"sqlite_version": sqlite3.sqlite_version}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        db_path = tmp_dir / "bench.sqlite3"
        seed_sec = build_v1_dataset(db_path)
        v1_size_mb = round(db_path.stat().st_size / (1024 * 1024), 2)

        writer = connect(db_path)
        t0 = time.perf_counter()
        migrate(writer)
        migrate_sec = round(time.perf_counter() - t0, 3)
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("VACUUM")
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        table_sizes = collect_table_sizes(writer)
        migrate_rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 2)
        writer.close()

        results["build"] = {
            "v1_seed_sec": round(seed_sec, 3),
            "v1_size_mb": v1_size_mb,
            "migrate_v1_to_current_sec": migrate_sec,
            "migrated_db_size_mb": round(db_path.stat().st_size / (1024 * 1024), 2),
            "post_migrate_peak_rss_mb": migrate_rss_mb,
            "top_objects_mb": table_sizes,
        }
        results["query_plans"] = _collect_query_plans(db_path)
        results["storage_latencies"] = _measure_storage_queries(db_path)
        boot_ms, http_stats = _measure_http(db_path)
        results["app_startup_ms"] = boot_ms
        results["http_e2e_latencies"] = http_stats
        ro_stats, rw_stats = _measure_concurrency(db_path)
        results["concurrent_reads_16_threads"] = ro_stats
        results["concurrent_read_write_mix"] = rw_stats
        results["maintenance"] = _measure_maintenance(db_path, tmp_dir)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
