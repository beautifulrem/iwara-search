"""Domain models shared by the crawler, the storage layer and the web layer."""

from __future__ import annotations

from collections import Counter
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
EntityKind = Literal["authors", "tags", "origins", "characters"]
RankingKind = Literal["authors", "tags", "origins", "characters", "categories"]
MovieStatus = Literal["active", "missing"]

SORT_MODES: tuple[SortMode, ...] = (
    "published_desc",
    "published_asc",
    "hot_desc",
    "popularity_desc",
    "favorites_desc",
    "favorites_asc",
    "views_desc",
    "views_asc",
)
DEFAULT_SORT: SortMode = "published_desc"
ENTITY_KINDS: tuple[EntityKind, ...] = ("authors", "tags", "origins", "characters")
RANKING_KINDS: tuple[RankingKind, ...] = ("characters", "authors", "tags", "origins", "categories")


# --- crawl side ------------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class EntityRef:
    source_id: int
    name: str
    url: str | None = None


@dataclass(slots=True, frozen=True)
class MovieListItem:
    source_site_id: int
    oreno3d_url: str
    title: str
    author_name: str | None
    thumbnail_url: str | None
    view_count: int | None
    favorite_count: int | None


@dataclass(slots=True, frozen=True)
class ListingPage:
    page: int
    last_page: int
    items: list[MovieListItem]


@dataclass(slots=True, frozen=True)
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
class CrawlerStats:
    """HTTP counters for one client lifetime (one sync run)."""

    requests: int = 0
    retries: int = 0
    throttled: int = 0
    status_codes: Counter[int] = field(default_factory=Counter)


@dataclass(slots=True, frozen=True)
class ListUpsertResult:
    movie_id: int
    is_new: bool
    list_changed: bool
    needs_detail: bool


# --- read side -------------------------------------------------------------------------------


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
    sort: SortMode = DEFAULT_SORT

    def to_query_dict(self) -> dict[str, str]:
        """Serialise to the canonical, minimal query-string form."""

        data: dict[str, str] = {}
        if self.q:
            data["q"] = self.q
        if self.title_mode != "all":
            data["title_mode"] = self.title_mode
        for name in ID_FILTER_FIELDS:
            values: list[int] = getattr(self, name)
            if values:
                data[name] = ",".join(str(item) for item in values)
        for name in ("published_from", "published_to"):
            text: str = getattr(self, name)
            if text:
                data[name] = text
        for name in RANGE_FILTER_FIELDS:
            number: int | None = getattr(self, name)
            if number is not None:
                data[name] = str(number)
        if self.sort != DEFAULT_SORT:
            data["sort"] = self.sort
        return data

    def active_filter_count(self) -> int:
        """How many refinement groups (besides the free-text query) are in effect."""

        count = sum(1 for name in ID_FILTER_FIELDS if getattr(self, name))
        count += 1 if (self.published_from or self.published_to) else 0
        count += 1 if (self.min_views is not None or self.max_views is not None) else 0
        count += 1 if (self.min_favorites is not None or self.max_favorites is not None) else 0
        return count


ID_FILTER_FIELDS: tuple[str, ...] = (
    "author_any",
    "author_not",
    "origin_any",
    "origin_not",
    "character_any",
    "character_not",
    "tag_all",
    "tag_any",
    "tag_not",
)
RANGE_FILTER_FIELDS: tuple[str, ...] = ("min_views", "max_views", "min_favorites", "max_favorites")
ID_FILTER_KIND: dict[str, EntityKind] = {
    "author_any": "authors",
    "author_not": "authors",
    "origin_any": "origins",
    "origin_not": "origins",
    "character_any": "characters",
    "character_not": "characters",
    "tag_all": "tags",
    "tag_any": "tags",
    "tag_not": "tags",
}


@dataclass(slots=True, frozen=True)
class EntityLink:
    id: int
    name: str


@dataclass(slots=True, frozen=True)
class MovieCard:
    source_site_id: int
    title: str
    thumbnail_url: str | None
    published_at: str | None
    view_count: int
    favorite_count: int
    author_name: str
    author_id: int | None
    tags: tuple[EntityLink, ...] = ()


@dataclass(slots=True, frozen=True)
class MovieDetailView:
    card: MovieCard
    oreno3d_url: str
    external_video_url: str | None
    author_comment: str | None
    status: MovieStatus
    detail_fetched_at: str | None
    tags: tuple[EntityLink, ...]
    origins: tuple[EntityLink, ...]
    characters: tuple[EntityLink, ...]


@dataclass(slots=True, frozen=True)
class SearchPage:
    items: list[MovieCard]
    total: int
    total_is_capped: bool
    page: int
    page_count: int


@dataclass(slots=True, frozen=True)
class RankingRow:
    kind: EntityKind
    source_id: int
    name: str
    movie_count: int
    total_views: int
    total_favorites: int
    popularity: int
    hot: float


@dataclass(slots=True, frozen=True)
class DatasetStatus:
    movie_count: int
    last_success_at: str | None
    last_run_at: str | None
    last_run_status: str | None
    last_run_requests: int = 0
    last_run_retries: int = 0
    last_run_throttled: int = 0
