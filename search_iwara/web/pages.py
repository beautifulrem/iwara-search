"""HTML pages: search, movie detail and ranking listings."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Final
from urllib.parse import parse_qsl, urlsplit

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from ..i18n import SUPPORTED_LANGS, Translator, build_translator
from ..models import (
    DEFAULT_RANKING_SORT,
    ID_FILTER_FIELDS,
    ID_FILTER_KIND,
    RANKING_KINDS,
    SORT_MODES,
    EntityKind,
    EntityLink,
    MovieDetailView,
    RankingKind,
    RankingRow,
    RankingSort,
    SearchFilters,
    SearchPage,
    SortMode,
)
from ..utils import MAX_SAFE_INTEGER, href_with_query, split_query_tokens, update_query_params
from .context import (
    ENTITY_SEARCH_PARAM,
    PAGE_VARY,
    ActiveFilter,
    AppState,
    BaseContext,
    DetailContext,
    FacetItem,
    FacetSection,
    FilterGroup,
    FilterTone,
    IndexContext,
    QuickPreset,
    RankingContext,
    RankingDep,
    RankingSortLink,
    RankingTab,
    SearchDep,
    StateDep,
    TaxonomyChip,
    TaxonomyRow,
    apply_lang_cookie,
    base_context,
    facet_workbench,
    not_modified,
    page_etag,
    pagination,
    request_lang,
    search_href,
)
from .formatting import SOURCE_TZ
from .query import MAX_IDS_PER_FILTER, RankingParams, SearchParams

router = APIRouter(include_in_schema=False)  # HTML pages are not part of the JSON API
QUICK_SORTS: Final[tuple[tuple[SortMode, str], ...]] = (
    ("published_desc", "clock"),
    ("hot_desc", "trending"),
    ("popularity_desc", "trophy"),
    ("favorites_desc", "heart"),
)
FACET_SECTIONS: Final[tuple[tuple[EntityKind, str, str], ...]] = (
    ("characters", "sparkles", "/characters"),
    ("tags", "tag", "/tags"),
    ("authors", "user", "/authors"),
    ("origins", "book", "/origins"),
)
PRIMARY_RANKING_KINDS: Final[tuple[RankingKind, ...]] = ("characters", "authors", "tags", "origins")
RANKING_ICONS: Final[dict[RankingKind, str]] = {
    "characters": "sparkles",
    "authors": "user",
    "tags": "tag",
    "origins": "book",
    "categories": "layers",
}
RANKING_SORT_OPTIONS: Final[tuple[tuple[RankingSort, str], ...]] = (
    ("popularity", "trophy"),
    ("hot", "trending"),
    ("movies", "layers"),
    ("favorites", "heart"),
    ("views", "eye"),
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
    apply_lang_cookie(request, response)
    response.headers["Vary"] = PAGE_VARY
    return response


# --- search ----------------------------------------------------------------------------------


def _csv(values: list[int]) -> str | None:
    return ",".join(str(item) for item in values) if values else None


def _field_operator_and_tone(name: str) -> tuple[str, FilterTone]:
    if name == "tag_all":
        return "ALL", "require"
    if name.endswith("_not"):
        return "NOT", "exclude"
    return "ANY", "include"


def _filter_groups(
    filters: SearchFilters, selected: dict[str, list[EntityLink]], unmatched: dict[str, list[str]]
) -> list[FilterGroup]:
    return [
        {
            "name": name,
            "kind": ID_FILTER_KIND[name],
            "api": f"/api/{ID_FILTER_KIND[name]}",
            "require": name == "tag_all",
            "negative": name.endswith("_not"),
            "selected": selected[name],
            "value": ",".join(str(item.id) for item in selected[name]),
            "pending_query": ", ".join(unmatched.get(name, ())),
        }
        for name in ID_FILTER_FIELDS
    ]


def _active_filters(
    filters: SearchFilters,
    selected: dict[str, list[EntityLink]],
    unmatched: dict[str, list[str]],
    tr: Translator,
) -> list[ActiveFilter]:
    """Removable chips for every refinement currently applied."""

    unmatched_params = {f"q_{k}": ", ".join(v) for k, v in unmatched.items() if v}
    base = {**filters.to_query_dict(), **unmatched_params}
    chips: list[ActiveFilter] = []
    if filters.title_mode == "any":
        chips.append(
            {
                "group": tr("filter.group.keyword"),
                "operator": "OR",
                "tone": "include",
                "label": tr("filter.keyword.mode_any"),
                "negative": False,
                "remove_href": search_href(base, title_mode=None),
            }
        )
    for name in ID_FILTER_FIELDS:
        operator, tone = _field_operator_and_tone(name)
        ids: list[int] = getattr(filters, name)
        for entity in selected[name]:
            remaining = ",".join(str(item) for item in ids if item != entity.id)
            chips.append(
                {
                    "group": tr(f"filter.{name}.title"),
                    "operator": operator,
                    "tone": tone,
                    "label": entity.name,
                    "negative": name.endswith("_not"),
                    "remove_href": search_href(base, **{name: remaining or None}),
                }
            )
        missing_list = unmatched.get(name, [])
        for idx, phrase in enumerate(missing_list):
            rem_phrases = [item for i, item in enumerate(missing_list) if i != idx]
            chips.append(
                {
                    "group": tr(f"filter.{name}.title"),
                    "operator": operator,
                    "tone": tone,
                    "label": phrase,
                    "negative": name.endswith("_not"),
                    "remove_href": search_href(base, **{f"q_{name}": ", ".join(rem_phrases) or None}),
                    "unmatched": True,
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
        if low_text and high_text:
            range_label = f"{low_text} – {high_text}"
        elif low_text:
            range_label = f"≥ {low_text}"
        else:
            range_label = f"≤ {high_text}"
        chips.append(
            {
                "group": tr(f"filter.range.{key}"),
                "operator": "",
                "tone": "neutral",
                "label": range_label,
                "negative": False,
                "remove_href": search_href(base, **dict.fromkeys(params)),
            }
        )
    return chips


def _quick_presets(filters: SearchFilters, query: dict[str, str], tr: Translator) -> list[QuickPreset]:
    today_jst = datetime.now(SOURCE_TZ).date()
    presets: list[QuickPreset] = []
    for days in (7, 30, 90):
        target = (today_jst - timedelta(days=days)).isoformat()
        active = filters.published_from == target and not filters.published_to
        presets.append(
            {
                "key": f"days_{days}",
                "label": tr(f"preset.days_{days}"),
                "href": search_href(query, published_from=None if active else target, published_to=None),
                "active": active,
                "field": "published_from",
                "clear_field": "published_to",
                "value": target,
            }
        )
    views_active = filters.min_views == 1000 and filters.max_views is None
    presets.append(
        {
            "key": "views_1k",
            "label": tr("preset.views_1k"),
            "href": search_href(query, min_views=None if views_active else 1000, max_views=None),
            "active": views_active,
            "field": "min_views",
            "clear_field": "max_views",
            "value": "1000",
        }
    )
    likes_active = filters.min_favorites == 100 and filters.max_favorites is None
    presets.append(
        {
            "key": "likes_100",
            "label": tr("preset.likes_100"),
            "href": search_href(query, min_favorites=None if likes_active else 100, max_favorites=None),
            "active": likes_active,
            "field": "min_favorites",
            "clear_field": "max_favorites",
            "value": "100",
        }
    )
    return presets


def _entity_toggle_hrefs(
    kind: EntityKind, entity_id: int, filters: SearchFilters, query: dict[str, str]
) -> tuple[str, str, bool, bool]:
    """Return ``(include_href, exclude_href, in_pos, in_neg)`` with mutual exclusion."""

    if kind == "tags":
        in_pos = (entity_id in filters.tag_all) or (entity_id in filters.tag_any)
        in_neg = entity_id in filters.tag_not
        if in_pos:
            include_href = search_href(
                query,
                tag_all=_csv([i for i in filters.tag_all if i != entity_id]),
                tag_any=_csv([i for i in filters.tag_any if i != entity_id]),
            )
        else:
            include_href = search_href(
                query,
                tag_all=_csv([*filters.tag_all, entity_id][:MAX_IDS_PER_FILTER]),
                tag_not=_csv([i for i in filters.tag_not if i != entity_id]),
            )
        if in_neg:
            exclude_href = search_href(query, tag_not=_csv([i for i in filters.tag_not if i != entity_id]))
        else:
            exclude_href = search_href(
                query,
                tag_not=_csv([*filters.tag_not, entity_id][:MAX_IDS_PER_FILTER]),
                tag_all=_csv([i for i in filters.tag_all if i != entity_id]),
                tag_any=_csv([i for i in filters.tag_any if i != entity_id]),
            )
        return include_href, exclude_href, in_pos, in_neg

    pos_field = ENTITY_SEARCH_PARAM[kind]
    neg_field = pos_field.replace("_any", "_not")
    pos_ids: list[int] = getattr(filters, pos_field)
    neg_ids: list[int] = getattr(filters, neg_field)
    in_pos = entity_id in pos_ids
    in_neg = entity_id in neg_ids
    if in_pos:
        include_href = search_href(query, **{pos_field: _csv([i for i in pos_ids if i != entity_id])})
    else:
        include_href = search_href(
            query,
            **{
                pos_field: _csv([*pos_ids, entity_id][:MAX_IDS_PER_FILTER]),
                neg_field: _csv([i for i in neg_ids if i != entity_id]),
            },
        )
    if in_neg:
        exclude_href = search_href(query, **{neg_field: _csv([i for i in neg_ids if i != entity_id])})
    else:
        exclude_href = search_href(
            query,
            **{
                neg_field: _csv([*neg_ids, entity_id][:MAX_IDS_PER_FILTER]),
                pos_field: _csv([i for i in pos_ids if i != entity_id]),
            },
        )
    return include_href, exclude_href, in_pos, in_neg


def _build_workbench(
    raw_workbench: dict[EntityKind, list[RankingRow]], filters: SearchFilters, query: dict[str, str]
) -> list[FacetSection]:
    sections: list[FacetSection] = []
    for kind, icon, more_href in FACET_SECTIONS:
        items: list[FacetItem] = []
        for row in raw_workbench.get(kind, ()):
            entity_id = row.source_id
            solo_href = search_href({}, **{ENTITY_SEARCH_PARAM[kind]: entity_id})
            include_href, exclude_href, in_pos, in_neg = _entity_toggle_hrefs(kind, entity_id, filters, query)
            items.append(
                {
                    "source_id": entity_id,
                    "name": row.name,
                    "movie_count": row.movie_count,
                    "solo_href": solo_href,
                    "include_href": include_href,
                    "exclude_href": exclude_href,
                    "include_active": in_pos,
                    "exclude_active": in_neg,
                }
            )
        sections.append({"kind": kind, "icon": icon, "more_href": more_href, "items": items})
    return sections


def _normalize_inverted_ranges(filters: SearchFilters) -> bool:
    swapped = False
    if filters.published_from and filters.published_to and filters.published_from > filters.published_to:
        filters.published_from, filters.published_to = filters.published_to, filters.published_from
        swapped = True
    if (
        filters.min_views is not None
        and filters.max_views is not None
        and filters.min_views > filters.max_views
    ):
        filters.min_views, filters.max_views = filters.max_views, filters.min_views
        swapped = True
    if (
        filters.min_favorites is not None
        and filters.max_favorites is not None
        and filters.min_favorites > filters.max_favorites
    ):
        filters.min_favorites, filters.max_favorites = filters.max_favorites, filters.min_favorites
        swapped = True
    return swapped


def _blank_param_redirect(
    request: Request,
    canonical: dict[str, str],
    unmatched: dict[str, list[str]],
    *,
    force_redirect: bool = False,
) -> RedirectResponse | None:
    needs_redirect = force_redirect or any(v == "" for v in request.query_params.values())
    if request.method != "GET" or unmatched or not needs_redirect:
        return None
    redirect_query = dict(canonical)
    lang_param = request.query_params.get("lang")
    if lang_param in SUPPORTED_LANGS:
        redirect_query["lang"] = lang_param
    resp = RedirectResponse(url=search_href(redirect_query), status_code=303)
    apply_lang_cookie(request, resp)
    return resp


def _resolve_workbench(
    state: AppState,
    search: SearchDep,
    rankings: RankingDep,
    *,
    filters: SearchFilters,
    query: dict[str, str],
    tr: Translator,
    impossible_match: bool,
) -> tuple[list[FacetSection], str]:
    if impossible_match:
        empty_wb: dict[EntityKind, list[RankingRow]] = {k: [] for k, _, _ in FACET_SECTIONS}
        return _build_workbench(empty_wb, filters, query), tr("workbench.filtered_note")
    if filters.q or filters.active_filter_count() > 0:
        pinned: dict[EntityKind, list[int]] = {
            "characters": [*filters.character_any, *filters.character_not],
            "tags": [*filters.tag_all, *filters.tag_any, *filters.tag_not],
            "authors": [*filters.author_any, *filters.author_not],
            "origins": [*filters.origin_any, *filters.origin_not],
        }
        raw_wb, sampled = search.facet_counts(filters, limit=5, pinned=pinned)
        note = tr("workbench.sampled_note" if sampled else "workbench.filtered_note")
        return _build_workbench(raw_wb, filters, query), note
    return _build_workbench(facet_workbench(state, rankings), filters, query), tr("workbench.corpus_note")


@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse, name="index")
def index(
    request: Request,
    params: Annotated[SearchParams, Query()],
    state: StateDep,
    search: SearchDep,
    rankings: RankingDep,
) -> Response:
    lang = request_lang(request)
    filters = params.to_filters()
    range_swapped = _normalize_inverted_ranges(filters)
    pending_queries = params.pending_entity_queries()
    has_blank = any(v == "" for v in request.query_params.values())
    etag = page_etag(request, state, lang)
    if (
        not (pending_queries or has_blank or range_swapped)
        and (cached := not_modified(request, etag)) is not None
    ):
        return cached

    tr = build_translator(lang)
    unmatched: dict[str, list[str]] = {}
    impossible_match = False
    for field_name, raw_text in pending_queries.items():
        matched_ids, missing_phrases = search.resolve_entity_names(ID_FILTER_KIND[field_name], raw_text)
        current_ids: list[int] = getattr(filters, field_name)
        for item_id in matched_ids:
            if item_id not in current_ids and len(current_ids) < MAX_IDS_PER_FILTER:
                current_ids.append(item_id)
        if missing_phrases:
            unmatched[field_name] = missing_phrases
            if field_name == "tag_all" or (not field_name.endswith("_not") and not current_ids):
                impossible_match = True

    settings = state.settings
    if impossible_match:
        result = SearchPage(items=[], total=0, total_is_capped=False, page=1, page_count=1)
    else:
        result = search.search(
            filters, page=params.page, page_size=settings.page_size, max_results=settings.max_result_window
        )
    query = filters.to_query_dict()
    canonical = dict(query, **({"page": str(result.page)} if result.page > 1 else {}))
    if (
        redirect_resp := _blank_param_redirect(
            request, canonical, unmatched, force_redirect=bool(pending_queries or range_swapped)
        )
    ) is not None:
        return redirect_resp

    selected = {
        name: search.resolve_entities(ID_FILTER_KIND[name], getattr(filters, name))
        for name in ID_FILTER_FIELDS
    }
    base = base_context(request, state, lang=lang, rankings=rankings, nav="search", canonical_query=canonical)
    empty_db = base["dataset"] is not None and base["dataset"].movie_count == 0
    active_chips = _active_filters(filters, selected, unmatched, tr)
    presets = _quick_presets(filters, query, tr)
    base["quick_presets"] = presets
    base["scoped_filter_count"] = len(active_chips)
    if not empty_db:
        wb_sections, wb_note = _resolve_workbench(
            state, search, rankings, filters=filters, query=query, tr=tr, impossible_match=impossible_match
        )
        base["workbench"] = wb_sections
        base["workbench_note"] = wb_note
    if filters.q:
        base["page_title"] = f"{tr('meta.search_title', q=filters.q)} · {tr('brand')}"
    context: IndexContext = {
        **base,
        "filters": filters,
        "highlight_terms": split_query_tokens(filters.q)[:8],
        "results": result,
        "query": query,
        "empty_database": empty_db,
        "filter_groups": _filter_groups(filters, selected, unmatched),
        "active_filters": active_chips,
        "active_filter_count": len(active_chips),
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


def _resolve_back_search_context(request: Request) -> tuple[str, bool, SearchFilters, dict[str, str]]:
    """Extract a validated, canonical same-origin search state from Referer when present."""

    empty_filters = SearchFilters()
    referer = request.headers.get("referer", "")
    if not referer:
        return "/", False, empty_filters, {}
    try:
        parts = urlsplit(referer)
    except ValueError:
        return "/", False, empty_filters, {}
    if parts.scheme not in ("http", "https") or parts.netloc != request.url.netloc or parts.path != "/":
        return "/", False, empty_filters, {}
    if not parts.query:
        return "/", True, empty_filters, {}
    raw_pairs = dict(parse_qsl(parts.query, keep_blank_values=False))
    try:
        parsed = SearchParams.model_validate(raw_pairs)
    except ValidationError:
        return "/", True, empty_filters, {}
    ref_filters = parsed.to_filters()
    ref_query = ref_filters.to_query_dict()
    back_query = dict(ref_query)
    if parsed.page > 1:
        back_query["page"] = str(parsed.page)
    return search_href(back_query), True, ref_filters, ref_query


def _make_taxonomy_chip(
    kind: EntityKind, entity_id: int | None, name: str, filters: SearchFilters, query: dict[str, str]
) -> TaxonomyChip:
    if entity_id is None:
        return {
            "id": None,
            "name": name,
            "kind": kind,
            "is_req": False,
            "solo_href": "",
            "include_href": "",
            "exclude_href": "",
            "include_active": False,
            "exclude_active": False,
        }
    solo_href = search_href({}, **{ENTITY_SEARCH_PARAM[kind]: entity_id})
    include_href, exclude_href, in_pos, in_neg = _entity_toggle_hrefs(kind, entity_id, filters, query)
    return {
        "id": entity_id,
        "name": name,
        "kind": kind,
        "is_req": kind == "tags",
        "solo_href": solo_href,
        "include_href": include_href,
        "exclude_href": exclude_href,
        "include_active": in_pos,
        "exclude_active": in_neg,
    }


def _detail_taxonomy(
    movie: MovieDetailView, filters: SearchFilters, query: dict[str, str]
) -> list[TaxonomyRow]:
    card = movie.card
    creator_items: list[TaxonomyChip] = []
    if card.author_id is not None:
        creator_items.append(_make_taxonomy_chip("authors", card.author_id, card.author_name, filters, query))
    elif card.author_name:
        creator_items.append(_make_taxonomy_chip("authors", None, card.author_name, filters, query))
    groups: tuple[tuple[str, str, EntityKind, tuple[EntityLink, ...]], ...] = (
        ("detail.origin", "book", "origins", movie.origins),
        ("detail.character", "sparkles", "characters", movie.characters),
        ("detail.tag", "tag", "tags", movie.tags),
    )
    rows: list[TaxonomyRow] = [{"label_key": "detail.creator", "icon": "user", "items": creator_items}]
    rows.extend(
        {
            "label_key": label_key,
            "icon": icon,
            "items": [_make_taxonomy_chip(kind, item.id, item.name, filters, query) for item in links],
        }
        for label_key, icon, kind, links in groups
    )
    return rows


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
    back_href, has_search_context, ref_filters, ref_query = _resolve_back_search_context(request)
    etag = page_etag(request, state, lang, extra=back_href)
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
        "back_search_href": back_href,
        "has_search_context": has_search_context,
        "taxonomy_rows": _detail_taxonomy(movie, ref_filters, ref_query),
    }
    return render(request, state, "movie_detail.html", context, etag=etag)


# --- rankings --------------------------------------------------------------------------------


def _ranking_tabs(active_kind: RankingKind) -> list[RankingTab]:
    kinds = PRIMARY_RANKING_KINDS if active_kind != "categories" else RANKING_KINDS
    return [
        {
            "kind": item,
            "icon": RANKING_ICONS[item],
            "href": f"/{item}",
            "active": item == active_kind,
        }
        for item in kinds
    ]


def _ranking_sorts(path: str, query: dict[str, str], active_sort: RankingSort) -> list[RankingSortLink]:
    return [
        {
            "value": mode,
            "icon": icon,
            "href": href_with_query(
                path,
                update_query_params(query, sort=None if mode == DEFAULT_RANKING_SORT else mode, page=None),
            ),
            "active": mode == active_sort,
        }
        for mode, icon in RANKING_SORT_OPTIONS
    ]


def _ranking_page(kind: RankingKind) -> Callable[..., Response]:
    path = f"/{kind}"

    def handler(
        request: Request,
        params: Annotated[RankingParams, Query()],
        state: StateDep,
        rankings: RankingDep,
    ) -> Response:
        lang = request_lang(request)
        needs_clean = any(v == "" for v in request.query_params.values()) or (
            request.query_params.get("sort") == DEFAULT_RANKING_SORT
        )
        if request.method == "GET" and needs_clean:
            clean_query: dict[str, str] = {}
            if params.q:
                clean_query["q"] = params.q
            if params.sort != DEFAULT_RANKING_SORT:
                clean_query["sort"] = params.sort
            if params.page > 1:
                clean_query["page"] = str(params.page)
            lang_param = request.query_params.get("lang")
            if lang_param in SUPPORTED_LANGS:
                clean_query["lang"] = lang_param
            resp = RedirectResponse(
                url=href_with_query(path, update_query_params(clean_query)), status_code=303
            )
            apply_lang_cookie(request, resp)
            return resp

        etag = page_etag(request, state, lang)
        if (cached := not_modified(request, etag)) is not None:
            return cached
        total = rankings.count(kind, q=params.q)
        page_total = max(1, -(-total // RANKING_PAGE_SIZE))
        page = min(params.page, page_total)
        offset = (page - 1) * RANKING_PAGE_SIZE
        items = rankings.top(kind, limit=RANKING_PAGE_SIZE, offset=offset, q=params.q, sort=params.sort)
        ranking_query: dict[str, str] = {}
        if params.q:
            ranking_query["q"] = params.q
        if params.sort != DEFAULT_RANKING_SORT:
            ranking_query["sort"] = params.sort
        canonical = dict(ranking_query, **({"page": str(page)} if page > 1 else {}))
        base = base_context(request, state, lang=lang, rankings=rankings, nav=kind, canonical_query=canonical)
        entity_title = base["tr"](f"entity.{kind}")
        base["page_title"] = (
            f"{params.q} · {entity_title} · {base['tr']('brand')}"
            if params.q
            else f"{entity_title} · {base['tr']('brand')}"
        )
        clear_q_href = (
            href_with_query(path, update_query_params(ranking_query, q=None, page=None)) if params.q else None
        )
        context: RankingContext = {
            **base,
            "entity_kind": kind,
            "ranking_tabs": _ranking_tabs(kind),
            "ranking_q": params.q,
            "ranking_sort": params.sort,
            "ranking_sorts": _ranking_sorts(path, ranking_query, params.sort),
            "clear_ranking_q_href": clear_q_href,
            "items": items,
            "rank_offset": offset,
            "total": total,
            "author_movies": (
                rankings.top_movies_by_author([item.source_id for item in items]) if kind == "authors" else {}
            ),
            "item_href": lambda item: search_href({}, **{ENTITY_SEARCH_PARAM[item.kind]: item.source_id}),
            "pagination": pagination(page, page_total, ranking_query, path=path),
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
