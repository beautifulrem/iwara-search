"""Query-string models for the search page.

Structural limits (length of ``q``, page range, list sizes) are enforced strictly — a
request beyond them gets a 422 page — while *semantically* bad values inside the limits
(``min_views=abc``, an unknown sort, a malformed date) are ignored, so a hand-edited or
stale URL still produces a useful result page instead of an error.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import DEFAULT_SORT, ID_FILTER_FIELDS, SORT_MODES, SearchFilters, SortMode, TitleMode
from ..utils import parse_bounded_int, parse_csv_ids

MAX_QUERY_LENGTH: Final = 200
MAX_IDS_PER_FILTER: Final = 20
MAX_PAGE: Final = 100_000
SORT_ALIASES: Final[dict[str, SortMode]] = {
    "hot": "hot_desc",
    "popularity": "popularity_desc",
    "latest": "published_desc",
    "favorites": "favorites_desc",
    "views": "views_desc",
}

IdList = Annotated[str, Field(max_length=MAX_IDS_PER_FILTER * 12)]
NumberText = Annotated[str, Field(max_length=24)]


class SearchParams(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    q: Annotated[str, Field(max_length=MAX_QUERY_LENGTH)] = ""
    title_mode: TitleMode = "all"
    author_any: IdList = ""
    author_not: IdList = ""
    origin_any: IdList = ""
    origin_not: IdList = ""
    character_any: IdList = ""
    character_not: IdList = ""
    tag_all: IdList = ""
    tag_any: IdList = ""
    tag_not: IdList = ""
    published_from: Annotated[str, Field(max_length=10)] = ""
    published_to: Annotated[str, Field(max_length=10)] = ""
    min_views: NumberText = ""
    max_views: NumberText = ""
    min_favorites: NumberText = ""
    max_favorites: NumberText = ""
    sort: SortMode = DEFAULT_SORT
    page: Annotated[int, Field(ge=1, le=MAX_PAGE)] = 1
    lang: Annotated[str | None, Field(max_length=16)] = None

    @field_validator("title_mode", mode="before")
    @classmethod
    def _title_mode(cls, value: Any) -> Any:
        return value if value in ("all", "any") else "all"

    @field_validator("sort", mode="before")
    @classmethod
    def _sort(cls, value: Any) -> Any:
        value = SORT_ALIASES.get(value, value)
        return value if value in SORT_MODES else DEFAULT_SORT

    @field_validator("published_from", "published_to", mode="after")
    @classmethod
    def _iso_date(cls, value: str) -> str:
        if not value:
            return ""
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            return ""

    def to_filters(self) -> SearchFilters:
        ids = {
            name: parse_csv_ids(getattr(self, name), limit=MAX_IDS_PER_FILTER) for name in ID_FILTER_FIELDS
        }
        return SearchFilters(
            q=self.q,
            title_mode=self.title_mode,
            published_from=self.published_from,
            published_to=self.published_to,
            min_views=parse_bounded_int(self.min_views),
            max_views=parse_bounded_int(self.max_views),
            min_favorites=parse_bounded_int(self.min_favorites),
            max_favorites=parse_bounded_int(self.max_favorites),
            sort=self.sort,
            **ids,
        )


class AutocompleteParams(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    query: Annotated[str, Field(max_length=100)] = ""
    limit: Annotated[int, Field(ge=1, le=20)] = 10
