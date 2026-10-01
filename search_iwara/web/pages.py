"""HTML pages: search, movie detail and ranking listings."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Final

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse, Response

from ..i18n import SUPPORTED_LANGS, Translator, build_translator
from ..models import (
    ID_FILTER_FIELDS,
    ID_FILTER_KIND,
    RANKING_KINDS,
    SORT_MODES,
    EntityLink,
    RankingKind,
    SearchFilters,
    SortMode,
)
from ..utils import MAX_SAFE_INTEGER, split_query_tokens
from .context import (
    ENTITY_SEARCH_PARAM,
    LANG_COOKIE,
    PAGE_VARY,
    ActiveFilter,
    AppState,
    BaseContext,
    DetailContext,
    FilterGroup,
    IndexContext,
    RankingContext,
    RankingDep,
    SearchDep,
    StateDep,
    base_context,
    not_modified,
    page_etag,
    pagination,
    request_lang,
    search_href,
)
from .query import MAX_PAGE, SearchParams

router = APIRouter(include_in_schema=False)  # HTML pages are not part of the JSON API
QUICK_SORTS: Final[tuple[tuple[SortMode, str], ...]] = (
    ("hot_desc", "trending"),
    ("popularity_desc", "trophy"),
    ("favorites_desc", "heart"),
    ("published_desc", "clock"),
)
RANKING_PAGE_SIZE: Final = 60


def render(
    request: Request,
    state: AppState,
    template: str,
    context: BaseContext,
    *,
    etag: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    response = state.templates.TemplateResponse(request, template, dict(context), status_code=status_code)
    if etag is not None:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "no-cache"
    lang_param = request.query_params.get("lang")
    if lang_param in SUPPORTED_LANGS:
        response.set_cookie(
            LANG_COOKIE, lang_param, max_age=60 * 60 * 24 * 365, samesite="lax", httponly=True
        )
    response.headers["Vary"] = PAGE_VARY
    return response


# --- search ----------------------------------------------------------------------------------


def _filter_groups(filters: SearchFilters, selected: dict[str, list[EntityLink]]) -> list[FilterGroup]:
    return [
        {
            "name": name,
            "kind": ID_FILTER_KIND[name],
            "api": f"/api/{ID_FILTER_KIND[name]}",
            "negative": name.endswith("_not"),
            "selected": selected[name],
            "value": ",".join(str(item.id) for item in selected[name]),
        }
        for name in ID_FILTER_FIELDS
    ]


def _active_filters(
    filters: SearchFilters, selected: dict[str, list[EntityLink]], tr: Translator
) -> list[ActiveFilter]:
    """Removable chips for every refinement currently applied."""

    base = filters.to_query_dict()
    chips: list[ActiveFilter] = []
    for name in ID_FILTER_FIELDS:
        ids: list[int] = getattr(filters, name)
        for entity in selected[name]:
            remaining = ",".join(str(item) for item in ids if item != entity.id)
            chips.append(
                {
                    "group": tr(f"filter.{name}.title"),
                    "label": entity.name,
                    "negative": name.endswith("_not"),
                    "remove_href": search_href(base, **{name: remaining or None}),
                }
            )
    ranges = (
        ("published", filters.published_from, filters.published_to, ("published_from", "published_to")),
        ("views", filters.min_views, filters.max_views, ("min_views", "max_views")),
        ("favorites", filters.min_favorites, filters.max_favorites, ("min_favorites", "max_favorites")),
    )
    for key, low, high, params in ranges:
        if low in (None, "") and high in (None, ""):
            continue
        low_text = "" if low in (None, "") else (f"{low:,}" if isinstance(low, int) else str(low))
        high_text = "" if high in (None, "") else (f"{high:,}" if isinstance(high, int) else str(high))
        chips.append(
            {
                "group": tr(f"filter.range.{key}"),
                "label": f"{low_text or '…'} – {high_text or '…'}",
                "negative": False,
                "remove_href": search_href(base, **dict.fromkeys(params)),
            }
        )
    return chips


@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse, name="index")
def index(
    request: Request,
    params: Annotated[SearchParams, Query()],
    state: StateDep,
    search: SearchDep,
    rankings: RankingDep,
) -> Response:
    lang = request_lang(request)
    etag = page_etag(request, state, lang)
    if (cached := not_modified(request, etag)) is not None:
        return cached
    tr = build_translator(lang)
    filters = params.to_filters()
    settings = state.settings
    result = search.search(
        filters, page=params.page, page_size=settings.page_size, max_results=settings.max_result_window
    )
    query = filters.to_query_dict()
    selected = {
        name: search.resolve_entities(ID_FILTER_KIND[name], getattr(filters, name))
        for name in ID_FILTER_FIELDS
    }
    canonical = dict(query, **({"page": str(result.page)} if result.page > 1 else {}))
    base = base_context(request, state, lang=lang, rankings=rankings, nav="search", canonical_query=canonical)
    if filters.q:
        base["page_title"] = f"{tr('meta.search_title', q=filters.q)} · {tr('brand')}"
    context: IndexContext = {
        **base,
        "filters": filters,
        "highlight_terms": split_query_tokens(filters.q)[:8],
        "results": result,
        "query": query,
        "empty_database": base["dataset"] is not None and base["dataset"].movie_count == 0,
        "filter_groups": _filter_groups(filters, selected),
        "active_filters": _active_filters(filters, selected, tr),
        "active_filter_count": filters.active_filter_count(),
        "clear_filters_href": search_href({}, q=filters.q or None, sort=query.get("sort")),
        "quick_sorts": [
            {
                "value": mode,
                "icon": icon,
                "href": search_href(query, sort=mode),
                "active": filters.sort == mode,
            }
            for mode, icon in QUICK_SORTS
        ],
        "sort_options": [
            {"value": mode, "href": search_href(query, sort=mode), "active": filters.sort == mode}
            for mode in SORT_MODES
        ],
        "pagination": pagination(result.page, result.page_count, query),
    }
    return render(request, state, "index.html", context, etag=etag)


# --- detail ----------------------------------------------------------------------------------


@router.api_route(
    "/movies/{source_site_id}", methods=["GET", "HEAD"], response_class=HTMLResponse, name="movie_detail"
)
def movie_detail(
    request: Request,
    source_site_id: Annotated[int, Path(ge=1, le=MAX_SAFE_INTEGER)],
    state: StateDep,
    search: SearchDep,
    rankings: RankingDep,
) -> Response:
    lang = request_lang(request)
    etag = page_etag(request, state, lang)
    if (cached := not_modified(request, etag)) is not None:
        return cached
    movie = search.get_movie(source_site_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="movie")
    base = base_context(
        request,
        state,
        lang=lang,
        rankings=rankings,
        title=movie.card.title,
        description=(movie.author_comment or movie.card.title)[:160],
        og_image=movie.card.thumbnail_url,
        nav="search",
    )
    context: DetailContext = {
        **base,
        "movie": movie,
        "related_movies": search.related_movies(source_site_id, limit=12),
    }
    return render(request, state, "movie_detail.html", context, etag=etag)


# --- rankings --------------------------------------------------------------------------------


def _ranking_page(kind: RankingKind) -> Callable[..., Response]:
    def handler(
        request: Request,
        state: StateDep,
        rankings: RankingDep,
        page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    ) -> Response:
        lang = request_lang(request)
        etag = page_etag(request, state, lang)
        if (cached := not_modified(request, etag)) is not None:
            return cached
        total = rankings.count(kind)
        page_total = max(1, -(-total // RANKING_PAGE_SIZE))
        page = min(page, page_total)
        offset = (page - 1) * RANKING_PAGE_SIZE
        items = rankings.top(kind, limit=RANKING_PAGE_SIZE, offset=offset)
        canonical = {"page": str(page)} if page > 1 else {}
        base = base_context(request, state, lang=lang, rankings=rankings, nav=kind, canonical_query=canonical)
        base["page_title"] = f"{base['tr'](f'entity.{kind}')} · {base['tr']('brand')}"
        context: RankingContext = {
            **base,
            "entity_kind": kind,
            "items": items,
            "rank_offset": offset,
            "total": total,
            "author_movies": (
                rankings.top_movies_by_author([item.source_id for item in items]) if kind == "authors" else {}
            ),
            "item_href": lambda item: search_href({}, **{ENTITY_SEARCH_PARAM[item.kind]: item.source_id}),
            "pagination": pagination(page, page_total, {}, path=f"/{kind}"),
        }
        return render(request, state, "entity_index.html", context, etag=etag)

    handler.__name__ = f"{kind}_index"
    return handler


for _kind in RANKING_KINDS:
    router.add_api_route(
        f"/{_kind}",
        _ranking_page(_kind),
        methods=["GET", "HEAD"],
        response_class=HTMLResponse,
        name=f"{_kind}_index",
    )
