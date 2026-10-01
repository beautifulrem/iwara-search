from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from search_iwara.config import Settings, get_settings
from search_iwara.storage import CrawlStore, SearchStore
from search_iwara.web import create_app
from tests.factories import seed

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)
STYLE_ATTR = re.compile(r"\sstyle\s*=", re.IGNORECASE)
EVENT_ATTR = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)


MARK = re.compile(r"</?mark>")


def assert_html(response, status: int = 200) -> str:  # type: ignore[no-untyped-def]
    """Response HTML with search-term highlighting removed, for plain text assertions."""

    assert response.status_code == status, response.text[:500]
    assert response.headers["content-type"].startswith("text/html")
    return MARK.sub("", str(response.text))


# --- search page ------------------------------------------------------------------------------


def test_index_lists_movies_with_sidebar(client: TestClient) -> None:
    html = assert_html(client.get("/"))
    for title in ("sunrise yelan mix", "sunset yelan dance", "キヴォトス"):
        assert title in html
    assert "Author Eleven" in html  # sidebar ranking + card author
    assert 'href="/categories"' in html
    assert "/?author_any=11" in html  # author names link to searches


@pytest.mark.parametrize(
    ("params", "present", "absent"),
    [
        ({"q": "yelan"}, ["sunrise yelan mix", "sunset yelan dance"], ["キヴォトス"]),
        ({"q": "我慢"}, ["キヴォトス"], ["sunrise yelan mix"]),
        ({"q": "Origin Prime"}, ["sunrise yelan mix"], ["キヴォトス"]),  # names are searchable
        (
            {"origin_any": "41", "character_any": "51", "min_views": "1000"},
            ["sunrise yelan mix"],
            ["sunset yelan dance"],
        ),
        ({"q": "yelan", "tag_not": "32"}, ["sunrise yelan mix", "sunset yelan dance"], ["キヴォトス"]),
        ({"sort": "hot"}, ["sunrise yelan mix"], []),
        # Date filters now apply with every sort, including the default "latest".
        ({"published_from": "2026-04-12"}, ["キヴォトス"], ["sunrise yelan mix"]),
        ({"published_to": "2026-04-11", "sort": "hot_desc"}, ["sunrise yelan mix"], ["キヴォトス"]),
        ({"min_favorites": "300", "sort": "favorites_desc"}, ["sunrise yelan mix"], ["sunset yelan dance"]),
    ],
)
def test_search_filters(
    client: TestClient, params: dict[str, str], present: list[str], absent: list[str]
) -> None:
    html = assert_html(client.get("/", params=params))
    for text in present:
        assert text in html
    for text in absent:
        assert text not in html


def test_active_filters_are_rendered_with_remove_links(client: TestClient) -> None:
    html = assert_html(client.get("/", params={"q": "yelan", "tag_not": "31", "min_views": "10"}))
    assert "Tag Alpha" in html  # resolved chip label
    assert 'name="tag_not" value="31"' in html  # filter form keeps state
    assert 'href="/?q=yelan&amp;min_views=10"' in html  # removing the tag chip keeps the rest


def test_hostile_or_malformed_input_never_errors(client: TestClient) -> None:
    for params in (
        {"min_views": "99999999999999999999"},
        {"max_favorites": "-5"},
        {"published_from": "2026-99-99"},
        {"sort": "drop table"},
        {"title_mode": "regex"},
        {"tag_any": "1,x,,2"},
        {"q": "\"unbalanced' OR 1=1 --"},
        {"q": "%_\\"},
        {"page": "999"},
    ):
        assert client.get("/", params=params).status_code == 200, params


@pytest.mark.parametrize(
    "params",
    [
        {"q": "x" * 201},
        {"page": "abc"},
        {"page": "0"},
        {"page": "99999999999999999999"},
        {"tag_all": ",".join(["1"] * 200)},
    ],
)
def test_structural_limits_return_html_422(client: TestClient, params: dict[str, str]) -> None:
    html = assert_html(client.get("/", params=params), 422)
    assert "422" in html


def test_empty_database_shows_onboarding(store: CrawlStore, settings: Settings) -> None:
    with TestClient(create_app(settings)) as empty:
        html = assert_html(empty.get("/"))
    assert "sync latest" in html


def test_head_requests(client: TestClient) -> None:
    for path in ("/", "/movies/200", "/authors", "/healthz"):
        response = client.head(path)
        assert response.status_code == 200, path
        assert response.content == b""


# --- detail & rankings ------------------------------------------------------------------------


def test_detail_page(client: TestClient) -> None:
    html = assert_html(client.get("/movies/200"))
    assert "Test comment" in html
    assert "https://www.iwara.tv/video/200" in html
    assert "/?origin_any=41" in html
    assert "/?character_any=51" in html
    assert "sunset yelan dance" in html  # related video
    assert 'property="og:image"' in html


def test_detail_never_renders_unsafe_urls(seeded: CrawlStore, settings: Settings) -> None:
    seeded.conn.execute(
        "UPDATE movies SET external_video_url = 'javascript:alert(1)//iwara', "
        "thumbnail_url = 'javascript:alert(2)' WHERE source_site_id = 200"
    )
    with TestClient(create_app(settings)) as client:
        html = assert_html(client.get("/movies/200"))
        listing = assert_html(client.get("/"))
    assert "javascript:" not in html
    assert "javascript:" not in listing


def test_missing_and_invalid_movies(client: TestClient) -> None:
    html = assert_html(client.get("/movies/999999"), 404)
    assert "404" in html
    assert_html(client.get("/movies/abc"), 422)
    assert_html(client.get("/nope"), 404)
    assert client.get("/nope", headers={"accept": "application/json"}).json() == {"detail": "Not Found"}


@pytest.mark.parametrize("kind", ["authors", "characters", "tags", "origins", "categories"])
def test_ranking_pages(client: TestClient, kind: str) -> None:
    html = assert_html(client.get(f"/{kind}"))
    assert any(name in html for name in ("Author Eleven", "Character One", "Tag Alpha", "Origin Prime"))
    assert_html(client.get(f"/{kind}", params={"page": "50"}))  # clamped to the last page
    assert_html(client.get(f"/{kind}", params={"page": "0"}), 422)


def test_author_ranking_shows_carousel(client: TestClient) -> None:
    html = assert_html(client.get("/authors"))
    assert "sunrise yelan mix" in html
    assert "/?author_any=11" in html


# --- API --------------------------------------------------------------------------------------


def test_autocomplete_api(client: TestClient) -> None:
    assert client.get("/api/authors", params={"query": "eleven"}).json() == [
        {"id": 11, "name": "Author Eleven"}
    ]
    assert client.get("/api/tags", params={"query": "alpha"}).json() == [{"id": 31, "name": "Tag Alpha"}]
    assert client.get("/api/origins", params={"query": "prime"}).json() == [
        {"id": 41, "name": "Origin Prime"}
    ]
    assert client.get("/api/characters", params={"query": "one"}).json() == [
        {"id": 51, "name": "Character One"}
    ]
    assert len(client.get("/api/tags", params={"limit": 1}).json()) == 1
    response = client.get("/api/tags", params={"query": "x" * 101})
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"
    assert client.get("/api/unknown").status_code == 404
    assert client.get("/api/tags").headers["cache-control"] == "public, max-age=60"


# --- i18n & SEO -------------------------------------------------------------------------------


def test_language_selection(client: TestClient) -> None:
    ja = client.get("/", params={"lang": "ja"})
    assert '<html lang="ja"' in assert_html(ja)
    assert "ui_lang=ja" in ja.headers["set-cookie"]
    assert '<html lang="ja"' in client.get("/").text  # cookie remembered
    client.cookies.clear()
    assert '<html lang="en"' in client.get("/", headers={"accept-language": "en-US,en;q=0.9"}).text
    assert '<html lang="zh-Hans"' in client.get("/", headers={"accept-language": "fr"}).text
    assert client.get("/").headers["vary"].startswith("Cookie, Accept-Language")


def test_seo_metadata(client: TestClient) -> None:
    html = assert_html(client.get("/", params={"q": "yelan", "lang": "en"}))
    # Each language version is canonical to itself and pinned with ?lang=; the bare URL
    # negotiates the language and is the x-default.
    assert '<link rel="canonical" href="http://testserver/?q=yelan&amp;lang=en"' in html
    assert 'hreflang="en" href="http://testserver/?q=yelan&amp;lang=en"' in html
    assert 'hreflang="zh-Hans" href="http://testserver/?q=yelan&amp;lang=zh-Hans"' in html
    assert 'hreflang="x-default" href="http://testserver/?q=yelan"' in html
    pinned = client.get("/", params={"q": "yelan", "lang": "zh-Hans"}).text
    assert '<link rel="canonical" href="http://testserver/?q=yelan&amp;lang=zh-Hans"' in pinned
    client.cookies.clear()  # the ?lang= requests above set the language cookie
    for accept in ("zh-CN", "en-US", "ja"):
        negotiated = client.get("/", params={"q": "yelan"}, headers={"accept-language": accept}).text
        # The negotiating URL is the x-default and canonical to itself, whatever it rendered.
        assert '<link rel="canonical" href="http://testserver/?q=yelan"' in negotiated
        assert 'hreflang="x-default" href="http://testserver/?q=yelan"' in negotiated
    assert 'hreflang="ja"' in html
    assert 'hreflang="x-default"' in html
    assert '<meta name="robots" content="noindex,nofollow"' in html
    assert '<meta name="description"' in html
    title = html.split("<title>")[1].split("</title>")[0]
    assert "yelan" in title


# --- security, caching, ops -------------------------------------------------------------------


def test_security_headers_and_csp_compliance(client: TestClient) -> None:
    for path in ("/", "/movies/200", "/authors", "/nope"):
        response = client.get(path)
        csp = response.headers["content-security-policy"]
        assert "script-src 'self'" in csp
        assert "unsafe-inline" not in csp
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        html = response.text
        assert not INLINE_SCRIPT.search(html), path
        assert not STYLE_ATTR.search(html), path
        assert not EVENT_ATTR.search(html), path
        assert "googleapis" not in html


def test_compression_and_static_caching(client: TestClient) -> None:
    page = client.get("/", headers={"accept-encoding": "gzip"})
    assert page.headers["content-encoding"] == "gzip"
    versioned = re.search(r"/static/([\w./-]+\.css)\?v=(\w+)", page.text)
    assert versioned is not None
    asset = client.get(f"/static/{versioned.group(1)}?v={versioned.group(2)}")
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get(f"/static/{versioned.group(1)}").headers["cache-control"] == "public, max-age=3600"
    assert client.get("/favicon.ico", follow_redirects=False).headers["location"] == "/static/favicon.svg"
    assert client.get("/static/favicon.svg").status_code == 200


def test_health_and_metrics(seeded: CrawlStore, db_path: Path) -> None:
    settings = get_settings(db_path=db_path, metrics_token="s3cret-token-0123456789")
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json()["status"] == "ok"
        client.get("/")
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"authorization": "Bearer wrong"}).status_code == 401
        metrics = client.get("/metrics", headers={"authorization": "Bearer s3cret-token-0123456789"}).text
        assert "search_iwara_movies 3.0" in metrics
        assert 'search_iwara_http_requests_total{method="GET",route="/",status="200"}' in metrics
        assert "search_iwara_last_sync_success_timestamp_seconds" in metrics

        writer = sqlite3.connect(db_path)
        writer.execute("PRAGMA user_version = 99")
        writer.close()
        assert client.get("/readyz").status_code == 503


def test_metrics_without_token_are_loopback_only(client: TestClient) -> None:
    assert client.get("/metrics").status_code == 404  # TestClient's peer is not loopback
    local = TestClient(client.app, client=("127.0.0.1", 50000))
    assert local.get("/metrics").status_code == 200


def test_robots_and_indexing(client: TestClient, seeded: CrawlStore, db_path: Path) -> None:
    assert client.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"
    open_settings = get_settings(db_path=db_path, allow_indexing=True, metrics_enabled=False)
    with TestClient(create_app(open_settings)) as public:
        assert "Disallow: /api/" in public.get("/robots.txt").text
        response = public.get("/")
        assert "x-robots-tag" not in response.headers
        assert '<meta name="robots" content="index,follow"' in response.text
        assert public.get("/metrics").status_code == 404


def test_unexpected_errors_render_500_page(
    seeded: CrawlStore, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(SearchStore, "get_movie", boom)
    with TestClient(create_app(settings), raise_server_exceptions=False) as failing:
        html = assert_html(failing.get("/movies/200"), 500)
    assert "kaboom" not in html  # no internals leaked
    assert "500" in html


def test_app_creates_database_on_first_start(tmp_path: Path) -> None:
    settings = get_settings(db_path=tmp_path / "fresh" / "new.sqlite3")
    with TestClient(create_app(settings)) as fresh:
        assert fresh.get("/readyz").status_code == 200
        assert_html(fresh.get("/"))
    seed_store = CrawlStore.open(settings.db_path)
    seed(seed_store)
    seed_store.close()


# --- round-3 regressions ----------------------------------------------------------------------


def test_unicode_digit_parameters_do_not_crash(client: TestClient) -> None:
    for params in ({"tag_any": "²"}, {"min_views": "²"}, {"author_not": "٣,1"}, {"max_favorites": "１"}):
        assert client.get("/", params=params).status_code == 200, params


def test_html_pages_support_conditional_requests(client: TestClient) -> None:
    for path in ("/", "/movies/200", "/authors"):
        first = client.get(path)
        etag = first.headers["etag"]
        assert etag.startswith('W/"')
        assert first.headers["cache-control"] == "no-cache"
        again = client.get(path, headers={"if-none-match": etag})
        assert again.status_code == 304
        assert again.content == b""
    assert client.get("/", params={"lang": "ja"}).headers["etag"] != client.get("/").headers["etag"]


def test_api_docs_are_opt_in(client: TestClient, seeded: CrawlStore, db_path: Path) -> None:
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404
    with TestClient(create_app(get_settings(db_path=db_path, api_docs_enabled=True))) as docs:
        page = docs.get("/api/docs")
        assert page.status_code == 200
        assert "cdn.jsdelivr.net" in page.headers["content-security-policy"]
        assert "cdn.jsdelivr.net" not in docs.get("/").headers["content-security-policy"]
        assert docs.get("/api/openapi.json").json()["info"]["title"] == "Search Iwara"


def test_sitemaps_when_indexing_is_allowed(client: TestClient, seeded: CrawlStore, db_path: Path) -> None:
    assert client.get("/sitemap.xml").status_code == 404
    with TestClient(create_app(get_settings(db_path=db_path, allow_indexing=True))) as public:
        assert "Sitemap: http://testserver/sitemap.xml" in public.get("/robots.txt").text
        index = public.get("/sitemap.xml")
        assert index.headers["content-type"].startswith("application/xml")
        assert "http://testserver/sitemap-movies-1.xml" in index.text
        pages_xml = public.get("/sitemap-pages.xml").text
        assert "http://testserver/authors" in pages_xml
        movies_xml = public.get("/sitemap-movies-1.xml").text
        assert "http://testserver/movies/200" in movies_xml
        assert "<lastmod>" in movies_xml
        assert public.get("/sitemap-movies-2.xml").status_code == 404


def test_structured_access_log(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="search_iwara.access"):
        client.get("/healthz")
    record = next(r for r in caplog.records if r.name == "search_iwara.access")
    assert record.__dict__["status"] == 200
    assert record.__dict__["route"] == "/healthz"
    assert record.__dict__["method"] == "GET"
    assert record.__dict__["duration_ms"] >= 0


def test_worker_threads_are_bounded(seeded: CrawlStore, db_path: Path) -> None:
    from anyio import to_thread

    with TestClient(create_app(get_settings(db_path=db_path, web_threads=5))) as bounded:
        assert bounded.get("/healthz").status_code == 200
        assert bounded.portal is not None
        tokens = bounded.portal.call(lambda: to_thread.current_default_thread_limiter().total_tokens)
    assert tokens == 5


def test_metrics_can_be_disabled(seeded: CrawlStore, db_path: Path) -> None:
    settings = get_settings(db_path=db_path, metrics_enabled=False)
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as local:
        assert local.get("/metrics").status_code == 404


def test_stable_pagination_with_equal_counts(store: CrawlStore, settings: Settings) -> None:
    from tests.factories import make_detail

    seed(
        store,
        tuple(
            make_detail(i, title=f"same {i}", views=5, favorites=5, published_at="2026-01-01 00:00")
            for i in range(1, 81)
        ),
    )
    with TestClient(create_app(settings)) as client:
        seen: list[str] = []
        for page in (1, 2, 3):
            html = client.get("/", params={"sort": "favorites_desc", "page": page}).text
            seen += re.findall(r'href="(?:http://testserver)?/movies/(\d+)"', html)
    unique = list(dict.fromkeys(seen))
    assert sorted(map(int, unique)) == list(range(1, 81))


# --- round-4 regressions ----------------------------------------------------------------------


def test_304_repeats_vary(client: TestClient) -> None:
    etag = client.get("/authors").headers["etag"]
    response = client.get("/authors", headers={"if-none-match": etag})
    assert response.status_code == 304
    assert response.headers["vary"] == "Cookie, Accept-Language, Accept-Encoding"
    full = client.get("/authors", headers={"accept-encoding": "gzip"})
    assert full.headers["vary"] == response.headers["vary"]


def test_sidebar_is_fresh_as_soon_as_the_etag_changes(client: TestClient, seeded: CrawlStore) -> None:
    from tests.factories import make_detail

    before = client.get("/")
    assert "Brand New Author" not in before.text
    seed(seeded, (make_detail(900, title="fresh upload", author=(99, "Brand New Author"), views=10**7),))
    run = seeded.start_run("latest")
    seeded.finish_run(run, status="success", counters={})
    after = client.get("/", headers={"if-none-match": before.headers["etag"]})
    assert after.status_code == 200  # new data version -> new validator
    assert "Brand New Author" in after.text  # and the cached sidebar is not stale


def test_sync_interval_gauge(seeded: CrawlStore, db_path: Path) -> None:
    settings = get_settings(db_path=db_path, sync_hours=4)
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as local:
        assert "search_iwara_sync_interval_seconds 14400.0" in local.get("/metrics").text
    assert get_settings(sync_interval_seconds=900, sync_hours=4).expected_sync_interval == 900
    assert get_settings().expected_sync_interval is None


def test_third_party_text_gets_lang_when_reliable(client: TestClient) -> None:
    english = client.get("/", params={"lang": "en"}).text
    assert re.search(r'<a href="[^"]*/movies/202"[^>]* lang="ja"', english)  # kana title
    assert not re.search(r'/movies/200"[^>]* lang=', english)  # Latin title: no attribute
    japanese = client.get("/", params={"lang": "ja"}).text
    assert not re.search(r'/movies/202"[^>]* lang="ja"', japanese)  # same as page language
    detail = client.get("/movies/202", params={"lang": "en"}).text
    assert '<h1 class="detail__title" lang="ja">' in detail
