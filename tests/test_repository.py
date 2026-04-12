from pathlib import Path

from search_iwara.db import Repository
from search_iwara.models import EntityRef, MovieDetail, SearchFilters


def make_detail(
    source_id: int,
    *,
    title: str,
    author: tuple[int, str],
    tags: list[tuple[int, str]],
    origins: list[tuple[int, str]] | None = None,
    characters: list[tuple[int, str]] | None = None,
    published_at: str = "2026-04-11 05:12",
) -> MovieDetail:
    return MovieDetail(
        source_site_id=source_id,
        oreno3d_url=f"https://oreno3d.com/movies/{source_id}",
        title=title,
        external_video_url=f"https://www.iwara.tv/video/{source_id}",
        author=EntityRef(source_id=author[0], name=author[1], url=f"https://oreno3d.com/authors/{author[0]}"),
        tags=[EntityRef(source_id=tag_id, name=name, url=f"https://oreno3d.com/tags/{tag_id}") for tag_id, name in tags],
        origins=[
            EntityRef(source_id=origin_id, name=name, url=f"https://oreno3d.com/origins/{origin_id}")
            for origin_id, name in (origins or [])
        ],
        characters=[
            EntityRef(source_id=character_id, name=name, url=f"https://oreno3d.com/characters/{character_id}")
            for character_id, name in (characters or [])
        ],
        thumbnail_url=f"https://oreno3d.com/storage/{source_id}.jpg",
        published_at=published_at,
        view_count=source_id * 10,
        favorite_count=source_id,
        author_comment=None,
    )


def test_repository_upsert_and_boolean_search(tmp_path: Path):
    repo = Repository.open(tmp_path / "repo.sqlite3")
    with repo.transaction():
        repo.apply_movie_detail(
            make_detail(
                101,
                title="amber night dance",
                author=(10, "Author A"),
                tags=[(1, "Tag One"), (2, "Tag Two")],
                origins=[(11, "Origin A")],
                characters=[(21, "Character A")],
            )
        )
        repo.apply_movie_detail(
            make_detail(
                102,
                title="amber dawn",
                author=(20, "Author B"),
                tags=[(2, "Tag Two"), (3, "Tag Three")],
                origins=[(12, "Origin B")],
                characters=[(22, "Character B")],
                published_at="2026-04-10 05:12",
            )
        )
        repo.apply_movie_detail(
            make_detail(
                103,
                title="moonlight parade",
                author=(10, "Author A"),
                tags=[(3, "Tag Three")],
                origins=[(11, "Origin A")],
                characters=[(23, "Character C")],
                published_at="2026-04-09 05:12",
            )
        )

    all_match = repo.search_movies(SearchFilters(q="amber night", title_mode="all"), page=1, page_size=20)
    assert [item["source_site_id"] for item in all_match["items"]] == [101]

    any_match = repo.search_movies(SearchFilters(q="amber night", title_mode="any"), page=1, page_size=20)
    assert [item["source_site_id"] for item in any_match["items"]] == [101, 102]

    by_author = repo.search_movies(SearchFilters(author_any=[10]), page=1, page_size=20)
    assert [item["source_site_id"] for item in by_author["items"]] == [101, 103]

    author_excluded = repo.search_movies(SearchFilters(author_not=[10]), page=1, page_size=20)
    assert [item["source_site_id"] for item in author_excluded["items"]] == [102]

    tag_all = repo.search_movies(SearchFilters(tag_all=[2, 3]), page=1, page_size=20)
    assert [item["source_site_id"] for item in tag_all["items"]] == [102]

    tag_any = repo.search_movies(SearchFilters(tag_any=[1, 3]), page=1, page_size=20)
    assert [item["source_site_id"] for item in tag_any["items"]] == [101, 102, 103]

    tag_not = repo.search_movies(SearchFilters(tag_not=[1]), page=1, page_size=20)
    assert [item["source_site_id"] for item in tag_not["items"]] == [102, 103]

    combined = repo.search_movies(
        SearchFilters(q="amber", title_mode="all", author_any=[20], tag_not=[1]),
        page=1,
        page_size=20,
    )
    assert [item["source_site_id"] for item in combined["items"]] == [102]

    by_origin = repo.search_movies(SearchFilters(origin_any=[11]), page=1, page_size=20)
    assert [item["source_site_id"] for item in by_origin["items"]] == [101, 103]

    origin_excluded = repo.search_movies(SearchFilters(origin_not=[11]), page=1, page_size=20)
    assert [item["source_site_id"] for item in origin_excluded["items"]] == [102]

    by_character = repo.search_movies(SearchFilters(character_any=[22]), page=1, page_size=20)
    assert [item["source_site_id"] for item in by_character["items"]] == [102]

    character_excluded = repo.search_movies(SearchFilters(character_not=[21]), page=1, page_size=20)
    assert [item["source_site_id"] for item in character_excluded["items"]] == [102, 103]

    date_range = repo.search_movies(
        SearchFilters(published_from="2026-04-10", published_to="2026-04-11"),
        page=1,
        page_size=20,
    )
    assert [item["source_site_id"] for item in date_range["items"]] == [101, 102]

    hot_range = repo.search_movies(
        SearchFilters(min_views=1020, max_views=1030, min_favorites=102, max_favorites=103),
        page=1,
        page_size=20,
    )
    assert [item["source_site_id"] for item in hot_range["items"]] == [102, 103]

    published_asc = repo.search_movies(SearchFilters(sort="published_asc"), page=1, page_size=20)
    assert [item["source_site_id"] for item in published_asc["items"]] == [103, 102, 101]

    views_desc = repo.search_movies(SearchFilters(sort="views_desc"), page=1, page_size=20)
    assert [item["source_site_id"] for item in views_desc["items"]] == [103, 102, 101]

    favorites_asc = repo.search_movies(SearchFilters(sort="favorites_asc"), page=1, page_size=20)
    assert [item["source_site_id"] for item in favorites_asc["items"]] == [101, 102, 103]

    repo.close()


def test_repository_title_search_falls_back_to_substring_matching(tmp_path: Path):
    repo = Repository.open(tmp_path / "repo-substring.sqlite3")
    with repo.transaction():
        repo.apply_movie_detail(
            make_detail(
                201,
                title="【MMD】潜入!射精我慢賭博!~キヴォトスのピンク色の闇を暴け!~",
                author=(30, "Author C"),
                tags=[(4, "Tag Four")],
            )
        )

    partial = repo.search_movies(SearchFilters(q="キヴォトス", title_mode="all"), page=1, page_size=20)
    assert [item["source_site_id"] for item in partial["items"]] == [201]

    middle_substring = repo.search_movies(SearchFilters(q="我慢", title_mode="all"), page=1, page_size=20)
    assert [item["source_site_id"] for item in middle_substring["items"]] == [201]

    exact = repo.search_movies(
        SearchFilters(q="【MMD】潜入！射精我慢賭博！～キヴォトスのピンク色の闇を暴け！～", title_mode="all"),
        page=1,
        page_size=20,
    )
    assert [item["source_site_id"] for item in exact["items"]] == [201]

    multi_token = repo.search_movies(SearchFilters(q="MMD キヴォトス", title_mode="all"), page=1, page_size=20)
    assert [item["source_site_id"] for item in multi_token["items"]] == [201]

    repo.close()


def test_repository_replaces_tag_links_without_duplicates(tmp_path: Path):
    repo = Repository.open(tmp_path / "repo-2.sqlite3")
    with repo.transaction():
        repo.apply_movie_detail(
            make_detail(
                101,
                title="alpha",
                author=(10, "Author A"),
                tags=[(1, "Tag One"), (2, "Tag Two")],
            )
        )
        repo.apply_movie_detail(
            make_detail(
                101,
                title="alpha updated",
                author=(10, "Author A"),
                tags=[(2, "Tag Two")],
            )
        )

    movie = repo.get_movie(101)
    assert movie is not None
    assert movie["title"] == "alpha updated"
    assert [tag["id"] for tag in movie["tags"]] == [2]
    repo.close()


def test_get_related_movies(tmp_path: Path):
    repo = Repository.open(tmp_path / "related.sqlite3")
    with repo.transaction():
        # Movie A: author=10, characters=[21], origins=[11], tags=[1,2]
        repo.apply_movie_detail(
            make_detail(
                101, title="movie A", author=(10, "Author A"),
                tags=[(1, "dance"), (2, "voice")],
                origins=[(11, "Genshin")],
                characters=[(21, "Amber")],
            )
        )
        # Movie B: same author=10, shared character=21, shared tag=1
        # Expected score: 10 (author) + 5 (character 21) + 1 (tag 1) = 16
        repo.apply_movie_detail(
            make_detail(
                102, title="movie B", author=(10, "Author A"),
                tags=[(1, "dance"), (3, "mmd")],
                origins=[(12, "Vocaloid")],
                characters=[(21, "Amber"), (22, "Lumine")],
            )
        )
        # Movie C: different author, shared origin=11, shared tag=2
        # Expected score: 0 (author) + 5 (origin 11) + 1 (tag 2) = 6
        repo.apply_movie_detail(
            make_detail(
                103, title="movie C", author=(20, "Author B"),
                tags=[(2, "voice"), (4, "r18")],
                origins=[(11, "Genshin")],
                characters=[(23, "Lisa")],
            )
        )
        # Movie D: no overlap at all
        # Expected score: 0
        repo.apply_movie_detail(
            make_detail(
                104, title="movie D", author=(30, "Author C"),
                tags=[(5, "solo")],
                origins=[(13, "Honkai")],
                characters=[(24, "Bronya")],
            )
        )

    related = repo.get_related_movies(101, limit=12)
    # B scores 16, C scores 6, D scores 0 (excluded)
    assert len(related) == 2
    assert related[0]["source_site_id"] == 102
    assert related[1]["source_site_id"] == 103
    # Verify card-compatible fields exist
    assert "title" in related[0]
    assert "thumbnail_url" in related[0]
    assert "view_count_display" in related[0]
    assert "favorite_count_display" in related[0]
    assert "author_name" in related[0]

    repo.close()
