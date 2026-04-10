from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import PACKAGE_ROOT, get_settings
from .db import Repository
from .models import SearchFilters
from .utils import pagination_window, parse_csv_ids, parse_optional_int, update_query_params


TEMPLATES = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))

SORT_ALIASES = {
    "hot": "hot_desc",
    "popularity": "popularity_desc",
    "latest": "published_desc",
    "favorites": "favorites_desc",
    "views": "views_desc",
}

VALID_SORTS = {
    "hot_desc",
    "popularity_desc",
    "published_desc",
    "published_asc",
    "favorites_desc",
    "favorites_asc",
    "views_desc",
    "views_asc",
}

ENTITY_LABELS = {
    "authors": "热门作者",
    "characters": "热门角色",
    "tags": "热门标签",
    "origins": "热门原作",
}


def _build_filters(
    *,
    q: str,
    title_mode: str,
    author_any: str,
    author_not: str,
    origin_any: str,
    origin_not: str,
    character_any: str,
    character_not: str,
    tag_all: str,
    tag_any: str,
    tag_not: str,
    published_from: str,
    published_to: str,
    min_views: str,
    max_views: str,
    min_favorites: str,
    max_favorites: str,
    sort: str,
) -> SearchFilters:
    normalized_sort = SORT_ALIASES.get(sort, sort)
    valid_sort = normalized_sort if normalized_sort in VALID_SORTS else "published_desc"

    # Strip filters that conflict with the chosen sort mode so the sort's
    # own dimension is not also used as a constraint.
    if valid_sort in ("published_desc", "hot_desc"):
        published_from = ""
        published_to = ""
    if valid_sort in ("favorites_desc", "popularity_desc", "hot_desc"):
        min_favorites = ""
        max_favorites = ""
    if valid_sort in ("popularity_desc", "hot_desc"):
        min_views = ""
        max_views = ""

    return SearchFilters(
        q=q.strip(),
        title_mode="any" if title_mode == "any" else "all",
        author_any=parse_csv_ids(author_any),
        author_not=parse_csv_ids(author_not),
        origin_any=parse_csv_ids(origin_any),
        origin_not=parse_csv_ids(origin_not),
        character_any=parse_csv_ids(character_any),
        character_not=parse_csv_ids(character_not),
        tag_all=parse_csv_ids(tag_all),
        tag_any=parse_csv_ids(tag_any),
        tag_not=parse_csv_ids(tag_not),
        published_from=published_from.strip(),
        published_to=published_to.strip(),
        min_views=parse_optional_int(min_views),
        max_views=parse_optional_int(max_views),
        min_favorites=parse_optional_int(min_favorites),
        max_favorites=parse_optional_int(max_favorites),
        sort=valid_sort,
    )


def _pagination_items(
    current_page: int,
    page_total: int,
    current_query: dict[str, str],
    *,
    base_path: str = "/",
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in pagination_window(current_page, page_total):
        if entry is None:
            items.append({"ellipsis": True})
            continue
        query = update_query_params(current_query, page=entry if entry > 1 else None)
        items.append(
            {
                "page": entry,
                "active": entry == current_page,
                "href": base_path if not query else f"{base_path}?{query}",
            }
        )
    return items


def create_app(db_path: str | Path | None = None) -> FastAPI:
    settings = get_settings(db_path)
    app = FastAPI(title="Search Iwara")
    app.mount("/static", StaticFiles(directory=str(PACKAGE_ROOT / "static")), name="static")

    def get_repo() -> Repository:
        repo = Repository.open(settings.db_path)
        try:
            yield repo
        finally:
            repo.close()

    @app.get("/", response_class=HTMLResponse, name="index")
    def index(
        request: Request,
        q: str = Query("", description="Title query"),
        title_mode: str = Query("all"),
        author_any: str = Query(""),
        author_not: str = Query(""),
        origin_any: str = Query(""),
        origin_not: str = Query(""),
        character_any: str = Query(""),
        character_not: str = Query(""),
        tag_all: str = Query(""),
        tag_any: str = Query(""),
        tag_not: str = Query(""),
        published_from: str = Query(""),
        published_to: str = Query(""),
        min_views: str = Query(""),
        max_views: str = Query(""),
        min_favorites: str = Query(""),
        max_favorites: str = Query(""),
        sort: str = Query("latest"),
        page: int = Query(1, ge=1),
        repo: Repository = Depends(get_repo),
    ) -> HTMLResponse:
        filters = _build_filters(
            q=q,
            title_mode=title_mode,
            author_any=author_any,
            author_not=author_not,
            origin_any=origin_any,
            origin_not=origin_not,
            character_any=character_any,
            character_not=character_not,
            tag_all=tag_all,
            tag_any=tag_any,
            tag_not=tag_not,
            published_from=published_from,
            published_to=published_to,
            min_views=min_views,
            max_views=max_views,
            min_favorites=min_favorites,
            max_favorites=max_favorites,
            sort=sort,
        )
        result = repo.search_movies(filters, page=page, page_size=settings.page_size)

        if page > result["page_count"] and result["total"] > 0:
            page = result["page_count"]
            result = repo.search_movies(filters, page=page, page_size=settings.page_size)

        current_query = filters.to_query_dict()
        sidebar = repo.sidebar_rankings()
        selected = {
            "author_any": repo.resolve_entities("authors", filters.author_any),
            "author_not": repo.resolve_entities("authors", filters.author_not),
            "origin_any": repo.resolve_entities("origins", filters.origin_any),
            "origin_not": repo.resolve_entities("origins", filters.origin_not),
            "character_any": repo.resolve_entities("characters", filters.character_any),
            "character_not": repo.resolve_entities("characters", filters.character_not),
            "tag_all": repo.resolve_entities("tags", filters.tag_all),
            "tag_any": repo.resolve_entities("tags", filters.tag_any),
            "tag_not": repo.resolve_entities("tags", filters.tag_not),
        }

        def search_href(**updates: Any) -> str:
            query = update_query_params(current_query, **updates)
            return "/" if not query else f"/?{query}"

        def fresh_search_href(**updates: Any) -> str:
            query = update_query_params({}, **updates)
            return "/" if not query else f"/?{query}"

        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "filters": filters,
                "filter_state": {
                    "author_any": author_any,
                    "author_not": author_not,
                    "origin_any": origin_any,
                    "origin_not": origin_not,
                    "character_any": character_any,
                    "character_not": character_not,
                    "tag_all": tag_all,
                    "tag_any": tag_any,
                    "tag_not": tag_not,
                    "published_from": filters.published_from,
                    "published_to": filters.published_to,
                    "min_views": "" if filters.min_views is None else str(filters.min_views),
                    "max_views": "" if filters.max_views is None else str(filters.max_views),
                    "min_favorites": "" if filters.min_favorites is None else str(filters.min_favorites),
                    "max_favorites": "" if filters.max_favorites is None else str(filters.max_favorites),
                },
                "selected": selected,
                "results": result["items"],
                "total": result["total"],
                "page": page,
                "page_count": result["page_count"],
                "pagination_items": _pagination_items(page, result["page_count"], current_query),
                "search_href": search_href,
                "fresh_search_href": fresh_search_href,
                "sidebar": sidebar,
            },
        )

    @app.get("/movies/{source_site_id}", response_class=HTMLResponse, name="movie_detail")
    def movie_detail(
        request: Request,
        source_site_id: int,
        repo: Repository = Depends(get_repo),
    ) -> HTMLResponse:
        movie = repo.get_movie(source_site_id)
        if movie is None:
            raise HTTPException(status_code=404, detail="Movie not found")

        def search_href(**updates: Any) -> str:
            query = update_query_params({}, **updates)
            return "/" if not query else f"/?{query}"

        return TEMPLATES.TemplateResponse(
            request,
            "movie_detail.html",
            {
                "request": request,
                "movie": movie,
                "search_href": search_href,
            },
        )

    @app.get("/api/authors", name="authors_autocomplete")
    def authors_autocomplete(
        query: str = Query(""),
        repo: Repository = Depends(get_repo),
    ) -> list[dict[str, Any]]:
        return repo.autocomplete_entities("authors", query)

    @app.get("/api/tags", name="tags_autocomplete")
    def tags_autocomplete(
        query: str = Query(""),
        repo: Repository = Depends(get_repo),
    ) -> list[dict[str, Any]]:
        return repo.autocomplete_entities("tags", query)

    @app.get("/api/origins", name="origins_autocomplete")
    def origins_autocomplete(
        query: str = Query(""),
        repo: Repository = Depends(get_repo),
    ) -> list[dict[str, Any]]:
        return repo.autocomplete_entities("origins", query)

    @app.get("/api/characters", name="characters_autocomplete")
    def characters_autocomplete(
        query: str = Query(""),
        repo: Repository = Depends(get_repo),
    ) -> list[dict[str, Any]]:
        return repo.autocomplete_entities("characters", query)

    @app.get("/authors", response_class=HTMLResponse, name="authors_index")
    @app.get("/characters", response_class=HTMLResponse, name="characters_index")
    @app.get("/tags", response_class=HTMLResponse, name="tags_index")
    @app.get("/origins", response_class=HTMLResponse, name="origins_index")
    def entity_index(
        request: Request,
        page: int = Query(1, ge=1),
        repo: Repository = Depends(get_repo),
    ) -> HTMLResponse:
        path = request.url.path.strip("/")
        if path not in ENTITY_LABELS:
            raise HTTPException(status_code=404, detail="Entity listing not found")
        per_page = 60
        offset = (page - 1) * per_page
        items = repo.list_entity_rankings(path, limit=per_page, offset=offset)
        total = len(repo.list_entity_rankings(path, limit=10_000, offset=0))
        page_count = max(1, (total + per_page - 1) // per_page)

        def search_href(**updates: Any) -> str:
            query = update_query_params({}, **updates)
            return "/" if not query else f"/?{query}"

        return TEMPLATES.TemplateResponse(
            request,
            "entity_index.html",
            {
                "request": request,
                "entity_kind": path,
                "entity_title": ENTITY_LABELS[path],
                "items": items,
                "page": page,
                "page_count": page_count,
                "pagination_items": _pagination_items(page, page_count, {}, base_path=f"/{path}"),
                "search_href": search_href,
            },
        )

    return app
