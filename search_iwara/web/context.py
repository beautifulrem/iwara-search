"""Request-scoped dependencies and the typed contexts handed to the templates.

Every template receives a ``TypedDict`` subclass of :class:`BaseContext`, so mypy checks that
each page provides exactly the keys its template reads.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Final, Literal, NotRequired, TypedDict, TypeVar, cast

from fastapi import Depends, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from ..config import Settings
from ..i18n import LANGUAGE_BY_CODE, LANGUAGES, SUPPORTED_LANGS, Translator, build_translator, resolve_lang
from ..models import (
    DatasetStatus,
    EntityKind,
    EntityLink,
    MovieCard,
    MovieDetailView,
    RankingKind,
    RankingRow,
    SearchFilters,
    SearchPage,
    SortMode,
)
from ..storage import RankingStore, ReadOnlyPool, SearchStore
from ..utils import href_with_query, pagination_window, update_query_params

T = TypeVar("T")
LANG_COOKIE: Final = "ui_lang"
PAGE_VARY: Final = "Cookie, Accept-Language"
ETAG_TIME_BUCKET_SECONDS: Final = 300  # relative times ("3 hours ago") shift slowly
FilterTone = Literal["require", "include", "exclude", "neutral"]

# ranking/entity kind -> the search parameter that filters by it
ENTITY_SEARCH_PARAM: Final[dict[EntityKind, str]] = {
    "authors": "author_any",
    "characters": "character_any",
    "origins": "origin_any",
    "tags": "tag_any",
}


class TTLCache:
    """Tiny thread-safe cache for data that only changes when a sync finishes."""

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._items: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, factory: Callable[[], T]) -> T:
        now = time.monotonic()
        with self._lock:
            hit = self._items.get(key)
            if hit is not None and now - hit[0] < self.ttl:
                return cast("T", hit[1])
        value = factory()
        with self._lock:
            self._items = {k: v for k, v in self._items.items() if now - v[0] < self.ttl}
            self._items[key] = (now, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


@dataclass(frozen=True, slots=True)
class AppState:
    settings: Settings
    pool: ReadOnlyPool
    templates: Jinja2Templates
    cache: TTLCache
    trigram: bool
    static_version: str


def app_state(request: Request) -> AppState:
    state: AppState = request.app.state.search_iwara
    return state


def search_store(state: Annotated[AppState, Depends(app_state)]) -> SearchStore:
    return SearchStore(state.pool.get(), trigram=state.trigram)


def ranking_store(state: Annotated[AppState, Depends(app_state)]) -> RankingStore:
    return RankingStore(state.pool.get())


StateDep = Annotated[AppState, Depends(app_state)]
SearchDep = Annotated[SearchStore, Depends(search_store)]
RankingDep = Annotated[RankingStore, Depends(ranking_store)]


# --- typed template contexts ------------------------------------------------------------------


class LanguageLink(TypedDict):
    code: str
    label: str
    html_lang: str
    href: str
    active: bool


class Alternate(TypedDict):
    hreflang: str
    href: str


class PageItem(TypedDict):
    page: NotRequired[int]
    href: NotRequired[str]
    active: NotRequired[bool]
    ellipsis: NotRequired[bool]


class Pagination(TypedDict):
    items: list[PageItem]
    prev: str | None
    next: str | None
    current: int
    total: int


class FilterGroup(TypedDict):
    name: str
    kind: EntityKind
    api: str
    require: bool
    negative: bool
    selected: list[EntityLink]
    value: str
    pending_query: str


class ActiveFilter(TypedDict):
    group: str
    operator: str
    tone: FilterTone
    label: str
    negative: bool
    remove_href: str


class QuickPreset(TypedDict):
    key: str
    label: str
    href: str
    active: bool
    field: str
    clear_field: str
    value: str


class FacetItem(TypedDict):
    source_id: int
    name: str
    movie_count: int
    solo_href: str
    include_href: str
    exclude_href: str
    include_active: bool
    exclude_active: bool


class FacetSection(TypedDict):
    kind: EntityKind
    icon: str
    more_href: str
    items: list[FacetItem]


class RankingTab(TypedDict):
    kind: RankingKind
    icon: str
    href: str
    active: bool


class SortLink(TypedDict):
    value: SortMode
    href: str
    active: bool
    icon: NotRequired[str]


class TaxonomyChip(TypedDict):
    id: int | None
    name: str
    kind: EntityKind
    is_req: bool
    solo_href: str
    include_href: str
    exclude_href: str
    include_active: bool
    exclude_active: bool


class TaxonomyRow(TypedDict):
    label_key: str
    icon: str
    items: list[TaxonomyChip]


class BaseContext(TypedDict):
    request: Request
    lang: str
    html_lang: str
    tr: Translator
    languages: list[LanguageLink]
    alternates: list[Alternate]
    canonical_url: str
    x_default_url: str
    page_title: str
    meta_description: str
    og_image: str | None
    robots: str
    nav: str | None
    header_query: str
    header_hidden: dict[str, str]
    clear_query_href: str | None
    scoped_filter_count: int
    workbench: list[FacetSection] | None
    quick_presets: list[QuickPreset]
    dataset: DatasetStatus | None
    entity_search_param: dict[EntityKind, str]


class IndexContext(BaseContext):
    filters: SearchFilters
    highlight_terms: list[str]
    results: SearchPage
    query: dict[str, str]
    empty_database: bool
    filter_groups: list[FilterGroup]
    active_filters: list[ActiveFilter]
    active_filter_count: int
    clear_filters_href: str
    quick_sorts: list[SortLink]
    sort_options: list[SortLink]
    pagination: Pagination


class DetailContext(BaseContext):
    movie: MovieDetailView
    related_movies: list[MovieCard]
    back_search_href: str
    has_search_context: bool
    taxonomy_rows: list[TaxonomyRow]


class RankingContext(BaseContext):
    entity_kind: RankingKind
    ranking_tabs: list[RankingTab]
    items: list[RankingRow]
    rank_offset: int
    total: int
    author_movies: dict[int, list[MovieCard]]
    item_href: Callable[[RankingRow], str]
    pagination: Pagination


class ErrorContext(BaseContext):
    status_code: int
    error_kind: str


# --- helpers ----------------------------------------------------------------------------------


def request_lang(request: Request) -> str:
    return resolve_lang(
        request.query_params.get("lang"),
        request.cookies.get(LANG_COOKIE),
        request.headers.get("accept-language"),
    )


def search_href(base: dict[str, str] | None = None, **updates: object) -> str:
    return href_with_query("/", update_query_params(base or {}, **updates))


def pagination(current: int, total: int, query: dict[str, str], *, path: str = "/") -> Pagination:
    def href(page: int) -> str:
        return href_with_query(path, update_query_params(query, page=page if page > 1 else None))

    items: list[PageItem] = []
    for entry in pagination_window(current, total):
        if entry is None:
            items.append({"ellipsis": True})
        else:
            items.append({"page": entry, "href": href(entry), "active": entry == current})
    return {
        "items": items,
        "prev": href(current - 1) if current > 1 else None,
        "next": href(current + 1) if current < total else None,
        "current": current,
        "total": total,
    }


def data_version(state: AppState) -> str:
    """Changes whenever a sync run starts/finishes or derived data is refreshed."""

    row = (
        state.pool.get()
        .execute(
            "SELECT (SELECT COALESCE(MAX(id), 0) FROM sync_runs), "
            "(SELECT value FROM app_meta WHERE key = 'derived_refreshed_at')"
        )
        .fetchone()
    )
    return f"{row[0]}:{row[1]}"


# Cached read models are keyed by the data version, so they can never be older than the ETag
# computed from the same version (the TTL only bounds memory, not freshness).
def facet_workbench(state: AppState, rankings: RankingStore) -> dict[EntityKind, list[RankingRow]]:
    return state.cache.get_or_set(f"workbench:{data_version(state)}", rankings.facet_workbench)


def dataset_status(state: AppState, rankings: RankingStore) -> DatasetStatus:
    return state.cache.get_or_set(f"dataset:{data_version(state)}", rankings.dataset_status)


def page_etag(request: Request, state: AppState, lang: str, *, extra: str = "") -> str:
    """Weak validator for an HTML page: data version + URL + language + assets + time bucket.

    The five-minute bucket keeps relative timestamps ("3 hours ago") reasonably fresh.
    """

    bucket = int(time.time() // ETAG_TIME_BUCKET_SECONDS)
    material = f"{data_version(state)}|{lang}|{request.url}|{state.static_version}|{bucket}|{extra}"
    return 'W/"' + hashlib.blake2b(material.encode(), digest_size=10).hexdigest() + '"'


def apply_lang_cookie(request: Request, response: Response) -> None:
    lang_param = request.query_params.get("lang")
    if lang_param in SUPPORTED_LANGS:
        response.set_cookie(
            LANG_COOKIE,
            lang_param,
            max_age=60 * 60 * 24 * 365,
            samesite="lax",
            httponly=True,
            secure=(request.url.scheme == "https"),
        )


def not_modified(request: Request, etag: str) -> Response | None:
    candidates = {tag.strip() for tag in request.headers.get("if-none-match", "").split(",")}
    if etag in candidates or "*" in candidates:
        # RFC 9110 §15.4.5: a 304 carries the same Vary/ETag/Cache-Control a 200 would,
        # and must still update the language cookie when ?lang= was explicitly requested.
        response = Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": "no-cache", "Vary": f"{PAGE_VARY}, Accept-Encoding"},
        )
        apply_lang_cookie(request, response)
        return response
    return None


def base_context(
    request: Request,
    state: AppState,
    *,
    lang: str,
    title: str | None = None,
    description: str | None = None,
    canonical_query: dict[str, str] | None = None,
    og_image: str | None = None,
    rankings: RankingStore | None = None,
    nav: str | None = None,
) -> BaseContext:
    """Everything ``base.html`` needs: language, SEO, navigation, sidebar and dataset status."""

    tr: Translator = build_translator(lang)
    path = request.url.path
    query = {key: value for key, value in (canonical_query or {}).items() if key != "lang"}

    def url_for_lang(code: str | None) -> str:
        """Absolute URL of this page pinned to ``code``; ``None`` is the negotiating URL.

        Every language version, the default one included, carries an explicit ``?lang=`` so
        the URL always returns that language; the bare URL negotiates and is the x-default.
        """

        lang_query = query if code is None else {**query, "lang": code}
        return str(request.url.replace(query=update_query_params(lang_query), fragment=""))

    source_params = canonical_query if (canonical_query is not None and path == "/") else request.query_params
    header_hidden = {
        key: value for key, value in source_params.items() if key not in {"q", "page", "lang"} and value
    }
    header_query = request.query_params.get("q", "").strip() if path == "/" else ""
    return {
        "request": request,
        "lang": lang,
        "html_lang": LANGUAGE_BY_CODE[lang].html_lang,
        "tr": tr,
        "languages": [
            {
                "code": item.code,
                "label": item.label,
                "html_lang": item.html_lang,
                # Switcher links always carry ?lang= so choosing the default language sticks.
                "href": href_with_query(path, update_query_params(query, lang=item.code)),
                "active": item.code == lang,
            }
            for item in LANGUAGES
        ],
        "alternates": [{"hreflang": item.html_lang, "href": url_for_lang(item.code)} for item in LANGUAGES],
        # Pages reached through ?lang= are canonical to that language version; the bare URL
        # negotiates the language and is the x-default, so it is canonical to itself.
        "canonical_url": url_for_lang(lang) if "lang" in request.query_params else url_for_lang(None),
        "x_default_url": url_for_lang(None),
        "page_title": f"{title} · {tr('brand')}" if title else f"{tr('brand')} · {tr('meta.tagline')}",
        "meta_description": description or tr("meta.description"),
        "og_image": og_image,
        "robots": "index,follow" if state.settings.allow_indexing else "noindex,nofollow",
        "nav": nav,
        "header_query": header_query,
        "header_hidden": header_hidden if path == "/" else {},
        "clear_query_href": search_href(query, q=None) if (path == "/" and header_query) else None,
        "scoped_filter_count": 0,
        "workbench": None,
        "quick_presets": [],
        "dataset": dataset_status(state, rankings) if rankings is not None else None,
        "entity_search_param": ENTITY_SEARCH_PARAM,
    }


def as_template_context(context: BaseContext) -> dict[str, Any]:
    return dict(context)
