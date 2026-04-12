from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SortMode = Literal[
    "published_desc",
    "published_asc",
    "favorites_desc",
    "favorites_asc",
    "views_desc",
    "views_asc",
    "hot_desc",
    "popularity_desc",
]
TitleMode = Literal["all", "any"]


@dataclass(slots=True, frozen=True)
class EntityRef:
    source_id: int
    name: str
    url: str | None = None


@dataclass(slots=True)
class MovieListItem:
    source_site_id: int
    oreno3d_url: str
    title: str
    author_name: str | None
    thumbnail_url: str | None
    view_count: int | None
    favorite_count: int | None


@dataclass(slots=True)
class ListingPage:
    page: int
    last_page: int
    items: list[MovieListItem]


@dataclass(slots=True)
class MovieDetail:
    source_site_id: int
    oreno3d_url: str
    title: str
    external_video_url: str | None
    author: EntityRef | None
    tags: list[EntityRef]
    origins: list[EntityRef]
    characters: list[EntityRef]
    thumbnail_url: str | None
    published_at: str | None
    view_count: int | None
    favorite_count: int | None
    author_comment: str | None


@dataclass(slots=True)
class ListUpsertResult:
    movie_id: int
    is_new: bool
    list_changed: bool
    needs_detail: bool


@dataclass(slots=True)
class SearchFilters:
    q: str = ""
    title_mode: TitleMode = "all"
    author_any: list[int] = field(default_factory=list)
    author_not: list[int] = field(default_factory=list)
    origin_any: list[int] = field(default_factory=list)
    origin_not: list[int] = field(default_factory=list)
    character_any: list[int] = field(default_factory=list)
    character_not: list[int] = field(default_factory=list)
    tag_all: list[int] = field(default_factory=list)
    tag_any: list[int] = field(default_factory=list)
    tag_not: list[int] = field(default_factory=list)
    published_from: str = ""
    published_to: str = ""
    min_views: int | None = None
    max_views: int | None = None
    min_favorites: int | None = None
    max_favorites: int | None = None
    sort: SortMode = "published_desc"

    def to_query_dict(self, *, page: int | None = None) -> dict[str, str]:
        data: dict[str, str] = {}
        if self.q:
            data["q"] = self.q
        if self.title_mode != "all":
            data["title_mode"] = self.title_mode
        if self.author_any:
            data["author_any"] = ",".join(str(item) for item in self.author_any)
        if self.author_not:
            data["author_not"] = ",".join(str(item) for item in self.author_not)
        if self.origin_any:
            data["origin_any"] = ",".join(str(item) for item in self.origin_any)
        if self.origin_not:
            data["origin_not"] = ",".join(str(item) for item in self.origin_not)
        if self.character_any:
            data["character_any"] = ",".join(str(item) for item in self.character_any)
        if self.character_not:
            data["character_not"] = ",".join(str(item) for item in self.character_not)
        if self.tag_all:
            data["tag_all"] = ",".join(str(item) for item in self.tag_all)
        if self.tag_any:
            data["tag_any"] = ",".join(str(item) for item in self.tag_any)
        if self.tag_not:
            data["tag_not"] = ",".join(str(item) for item in self.tag_not)
        if self.published_from:
            data["published_from"] = self.published_from
        if self.published_to:
            data["published_to"] = self.published_to
        if self.min_views is not None:
            data["min_views"] = str(self.min_views)
        if self.max_views is not None:
            data["max_views"] = str(self.max_views)
        if self.min_favorites is not None:
            data["min_favorites"] = str(self.min_favorites)
        if self.max_favorites is not None:
            data["max_favorites"] = str(self.max_favorites)
        if self.sort != "published_desc":
            data["sort"] = self.sort
        if page is not None and page > 1:
            data["page"] = str(page)
        return data
