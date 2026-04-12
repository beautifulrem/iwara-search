from pathlib import Path

from fastapi.testclient import TestClient

from search_iwara.models import EntityRef, MovieDetail
from search_iwara.web import create_app
from search_iwara.db import Repository


def seed_db(db_path: Path) -> None:
    repo = Repository.open(db_path)
    with repo.transaction():
        repo.apply_movie_detail(
            MovieDetail(
                source_site_id=200,
                oreno3d_url="https://oreno3d.com/movies/200",
                external_video_url="https://www.iwara.tv/video/200",
                title="sunrise yelan mix",
                author=EntityRef(11, "Author Eleven", "https://oreno3d.com/authors/11"),
                tags=[EntityRef(31, "Tag Alpha", "https://oreno3d.com/tags/31")],
                origins=[EntityRef(41, "Origin Prime", "https://oreno3d.com/origins/41")],
                characters=[EntityRef(51, "Character One", "https://oreno3d.com/characters/51")],
                thumbnail_url="https://oreno3d.com/storage/200.jpg",
                published_at="2026-04-11 05:12",
                view_count=1234,
                favorite_count=321,
                author_comment="Test comment",
            )
        )
        repo.apply_movie_detail(
            MovieDetail(
                source_site_id=201,
                oreno3d_url="https://oreno3d.com/movies/201",
                external_video_url="https://www.iwara.tv/video/201",
                title="sunset yelan dance",
                author=EntityRef(11, "Author Eleven", "https://oreno3d.com/authors/11"),
                tags=[EntityRef(31, "Tag Alpha", "https://oreno3d.com/tags/31")],
                origins=[EntityRef(41, "Origin Prime", "https://oreno3d.com/origins/41")],
                characters=[EntityRef(51, "Character One", "https://oreno3d.com/characters/51")],
                thumbnail_url="https://oreno3d.com/storage/201.jpg",
                published_at="2026-04-11 06:00",
                view_count=500,
                favorite_count=100,
                author_comment="Another comment",
            )
        )
        repo.apply_movie_detail(
            MovieDetail(
                source_site_id=202,
                oreno3d_url="https://oreno3d.com/movies/202",
                external_video_url="https://www.iwara.tv/video/202",
                title="【MMD】潜入!射精我慢賭博!~キヴォトスのピンク色の闇を暴け!~",
                author=EntityRef(12, "Author Twelve", "https://oreno3d.com/authors/12"),
                tags=[EntityRef(32, "Tag Beta", "https://oreno3d.com/tags/32")],
                origins=[EntityRef(42, "Origin Blue Archive", "https://oreno3d.com/origins/42")],
                characters=[EntityRef(52, "Character Two", "https://oreno3d.com/characters/52")],
                thumbnail_url="https://oreno3d.com/storage/202.jpg",
                published_at="2026-04-12 06:00",
                view_count=888,
                favorite_count=222,
                author_comment="JP title test",
            )
        )
    repo.close()


def test_web_search_and_detail_routes(tmp_path: Path):
    db_path = tmp_path / "web.sqlite3"
    seed_db(db_path)

    app = create_app(db_path)
    client = TestClient(app)

    response = client.get("/", params={"q": "yelan", "title_mode": "all"})
    assert response.status_code == 200
    assert "sunrise yelan mix" in response.text
    assert "Tag Alpha" in response.text
    assert "热门角色" in response.text
    assert "热门作者" in response.text
    assert "热门分类" in response.text
    assert 'href="/categories"' in response.text

    origin_filter = client.get("/", params={"origin_any": "41", "character_any": "51", "min_views": "1000"})
    assert origin_filter.status_code == 200
    assert "sunrise yelan mix" in origin_filter.text

    hot_alias = client.get("/", params={"sort": "hot"})
    assert hot_alias.status_code == 200
    assert "飙升" in hot_alias.text

    jp_title = client.get("/", params={"q": "キヴォトス", "title_mode": "all"})
    assert jp_title.status_code == 200
    assert "【MMD】潜入!射精我慢賭博!~キヴォトスのピンク色の闇を暴け!~" in jp_title.text

    middle_substring = client.get("/", params={"q": "我慢", "title_mode": "all"})
    assert middle_substring.status_code == 200
    assert "【MMD】潜入!射精我慢賭博!~キヴォトスのピンク色の闇を暴け!~" in middle_substring.text

    detail = client.get("/movies/200")
    assert detail.status_code == 200
    assert "Test comment" in detail.text
    assert "https://www.iwara.tv/video/200" in detail.text
    assert "/?origin_any=41" in detail.text
    assert "/?character_any=51" in detail.text
    assert "theme-toggle" in detail.text
    assert "热门角色" in detail.text

    authors = client.get("/api/authors", params={"query": "eleven"})
    assert authors.status_code == 200
    assert authors.json() == [{"id": 11, "name": "Author Eleven"}]

    tags = client.get("/api/tags", params={"query": "alpha"})
    assert tags.status_code == 200
    assert tags.json() == [{"id": 31, "name": "Tag Alpha"}]

    origins = client.get("/api/origins", params={"query": "prime"})
    assert origins.status_code == 200
    assert origins.json() == [{"id": 41, "name": "Origin Prime"}]

    characters = client.get("/api/characters", params={"query": "one"})
    assert characters.status_code == 200
    assert characters.json() == [{"id": 51, "name": "Character One"}]

    authors_page = client.get("/authors")
    assert authors_page.status_code == 200
    assert "热门作者" in authors_page.text
    assert "Author Eleven" in authors_page.text
    assert "热门角色" in authors_page.text

    characters_page = client.get("/characters")
    assert characters_page.status_code == 200
    assert "热门角色" in characters_page.text
    assert "Character One" in characters_page.text

    categories_page = client.get("/categories")
    assert categories_page.status_code == 200
    assert "热门分类" in categories_page.text
    assert "Tag Alpha" in categories_page.text or "Origin Prime" in categories_page.text

    ja_page = client.get("/", params={"lang": "ja"})
    assert ja_page.status_code == 200
    assert "人気キャラ" in ja_page.text
    assert "急上昇" in ja_page.text
    assert "フィルター" in ja_page.text


def test_detail_page_shows_related_movies(tmp_path: Path):
    db_path = tmp_path / "web.sqlite3"
    seed_db(db_path)

    app = create_app(db_path)
    client = TestClient(app)

    detail = client.get("/movies/200")
    assert detail.status_code == 200
    assert "相关视频" in detail.text
    assert "sunset yelan dance" in detail.text
