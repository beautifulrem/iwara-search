"""Test data builders shared by the test modules."""

from __future__ import annotations

from search_iwara.models import EntityRef, MovieDetail
from search_iwara.storage import CrawlStore


def make_detail(
    source_id: int,
    *,
    title: str,
    author: tuple[int, str] | None = (10, "Author A"),
    tags: list[tuple[int, str]] | None = None,
    origins: list[tuple[int, str]] | None = None,
    characters: list[tuple[int, str]] | None = None,
    published_at: str | None = "2026-04-11 05:12",
    views: int | None = None,
    favorites: int | None = None,
    comment: str | None = None,
) -> MovieDetail:
    def refs(kind: str, items: list[tuple[int, str]] | None) -> list[EntityRef]:
        return [EntityRef(i, name, f"https://oreno3d.com/{kind}/{i}") for i, name in items or []]

    return MovieDetail(
        source_site_id=source_id,
        oreno3d_url=f"https://oreno3d.com/movies/{source_id}",
        title=title,
        external_video_url=f"https://www.iwara.tv/video/{source_id}",
        author=None
        if author is None
        else EntityRef(author[0], author[1], f"https://oreno3d.com/authors/{author[0]}"),
        tags=refs("tags", tags),
        origins=refs("origins", origins),
        characters=refs("characters", characters),
        thumbnail_url=f"https://oreno3d.com/storage/{source_id}.jpg",
        published_at=published_at,
        view_count=source_id * 10 if views is None else views,
        favorite_count=source_id if favorites is None else favorites,
        author_comment=comment,
    )


SAMPLE_MOVIES = (
    make_detail(
        200,
        title="sunrise yelan mix",
        author=(11, "Author Eleven"),
        tags=[(31, "Tag Alpha")],
        origins=[(41, "Origin Prime")],
        characters=[(51, "Character One")],
        published_at="2026-04-11 05:12",
        views=1234,
        favorites=321,
        comment="Test comment",
    ),
    make_detail(
        201,
        title="sunset yelan dance",
        author=(11, "Author Eleven"),
        tags=[(31, "Tag Alpha")],
        origins=[(41, "Origin Prime")],
        characters=[(51, "Character One")],
        published_at="2026-04-11 06:00",
        views=500,
        favorites=100,
    ),
    make_detail(
        202,
        title="【MMD】潜入!射精我慢賭博!~キヴォトスのピンク色の闇を暴け!~",
        author=(12, "Author Twelve"),
        tags=[(32, "Tag Beta")],
        origins=[(42, "Origin Blue Archive")],
        characters=[(52, "Character Two")],
        published_at="2026-04-12 06:00",
        views=888,
        favorites=222,
    ),
)


def seed(store: CrawlStore, movies: tuple[MovieDetail, ...] = SAMPLE_MOVIES) -> None:
    with store.transaction():
        for movie in movies:
            store.apply_movie_detail(movie)
    store.refresh_derived()
