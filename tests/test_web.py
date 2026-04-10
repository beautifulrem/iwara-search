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
    assert "人気キャラ" in response.text
    assert "人気作者" in response.text
    assert "人気カテゴリ" in response.text

    origin_filter = client.get("/", params={"origin_any": "41", "character_any": "51", "min_views": "1000"})
    assert origin_filter.status_code == 200
    assert "sunrise yelan mix" in origin_filter.text

    hot_alias = client.get("/", params={"sort": "hot"})
    assert hot_alias.status_code == 200
    assert "急上昇" in hot_alias.text

    detail = client.get("/movies/200")
    assert detail.status_code == 200
    assert "Test comment" in detail.text
    assert "https://www.iwara.tv/video/200" in detail.text
    assert "/?origin_any=41" in detail.text
    assert "/?character_any=51" in detail.text

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

    characters_page = client.get("/characters")
    assert characters_page.status_code == 200
    assert "热门角色" in characters_page.text
    assert "Character One" in characters_page.text
