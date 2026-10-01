"""FastAPI application factory."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from anyio import to_thread
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from jinja2.runtime import Context
from markupsafe import Markup
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from .. import __version__
from ..config import PACKAGE_ROOT, Settings, get_settings
from ..parsers import SOURCE_HOSTS, VIDEO_HOSTS
from ..storage import RankingStore, ReadOnlyPool, connect, migrate
from ..storage.search_store import uses_trigram
from ..utils import safe_url
from . import api, ops, pages
from .context import AppState, ErrorContext, TTLCache, base_context, request_lang
from .formatting import (
    format_compact,
    format_number,
    format_timestamp,
    highlight,
    iso_datetime,
    lang_attribute,
    relative_time,
)
from .metrics import AppMetrics, ObservabilityMiddleware
from .security import SecurityHeadersMiddleware

logger = logging.getLogger(__name__)
STATIC_DIR = PACKAGE_ROOT / "static"
TEMPLATES_DIR = PACKAGE_ROOT / "templates"


class CachedStaticFiles(StaticFiles):
    """Versioned assets (``?v=<hash>``) are immutable; unversioned ones get a short TTL."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            versioned = b"v=" in scope.get("query_string", b"")
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable" if versioned else "public, max-age=3600"
            )
        return response


def static_fingerprint(directory: Path = STATIC_DIR) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def build_templates(version: str) -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    env = templates.env
    env.trim_blocks = True
    env.lstrip_blocks = True

    @pass_context
    def compact(context: Context, value: int | None) -> str:
        return format_compact(value, context["lang"])

    @pass_context
    def lang_attr(context: Context, value: str | None) -> Markup:
        return lang_attribute(value, context["lang"])

    @pass_context
    def reltime(context: Context, value: str | None) -> str:
        return relative_time(value, context["lang"])

    def safe_href(value: str | None) -> str:
        """Defence in depth: only https links to the source/video hosts ever reach an href/src."""

        return safe_url(value, SOURCE_HOSTS + VIDEO_HOSTS) or ""

    env.filters.update(
        safe_href=safe_href,
        highlight=highlight,
        lang_attr=lang_attr,
        number=format_number,
        compact=compact,
        reltime=reltime,
        iso_datetime=iso_datetime,
        timestamp=format_timestamp,
    )
    env.globals.update(static_url=lambda path: f"/static/{path}?v={version}", app_version=__version__)
    return templates


def _wants_html(request: Request) -> bool:
    if request.url.path.startswith(("/api/", "/healthz", "/readyz", "/metrics")):
        return False
    return "application/json" not in request.headers.get("accept", "")


def _error_page(request: Request, status_code: int, *, detail: Any = None) -> Response:
    if not _wants_html(request):
        return JSONResponse({"detail": detail or "error"}, status_code=status_code)
    state: AppState = request.app.state.search_iwara
    lang = request_lang(request)
    base = base_context(request, state, lang=lang)
    base["page_title"] = f"{status_code} · {base['tr']('brand')}"
    context: ErrorContext = {
        **base,
        "status_code": status_code,
        "error_kind": {404: "not_found", 405: "not_allowed", 422: "invalid"}.get(status_code, "server"),
    }
    return state.templates.TemplateResponse(request, "error.html", dict(context), status_code=status_code)


def create_app(settings: Settings | None = None, *, db_path: str | Path | None = None) -> FastAPI:
    settings = settings or get_settings(db_path)
    version = static_fingerprint()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        writer = connect(settings.db_path)
        try:
            applied = migrate(writer)
            trigram = uses_trigram(writer)
        finally:
            writer.close()
        if applied:
            logger.info("database migrated", extra={"applied": applied, "db": str(settings.db_path)})
        # Bound the sync-endpoint thread pool (default 40): each worker thread keeps its own
        # read-only SQLite connection, so this also bounds connection count and page cache.
        to_thread.current_default_thread_limiter().total_tokens = settings.web_threads
        pool = ReadOnlyPool(settings.db_path)
        app.state.search_iwara = AppState(
            settings=settings,
            pool=pool,
            templates=build_templates(version),
            cache=TTLCache(60.0),
            trigram=trigram,
            static_version=version,
        )
        unregister = app.state.metrics.register_dataset(
            lambda: RankingStore(pool.get()).dataset_status(), sync_interval=settings.expected_sync_interval
        )
        try:
            yield
        finally:
            unregister()
            pool.close()

    app = FastAPI(
        title="Search Iwara",
        version=__version__,
        lifespan=lifespan,
        # The interactive docs load Swagger UI from a CDN; they are opt-in (see security.py).
        docs_url="/api/docs" if settings.api_docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.api_docs_enabled else None,
    )
    app.state.metrics = AppMetrics()

    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
    app.add_middleware(
        SecurityHeadersMiddleware,
        allow_indexing=settings.allow_indexing,
        docs_path="/api/docs" if settings.api_docs_enabled else None,
    )
    app.add_middleware(
        ObservabilityMiddleware, metrics=app.state.metrics if settings.metrics_enabled else None
    )

    app.mount("/static", CachedStaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(pages.router)
    app.include_router(api.router)
    app.include_router(ops.router)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        return _error_page(request, exc.status_code, detail=exc.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Response:
        if not _wants_html(request):
            return JSONResponse({"detail": exc.errors()}, status_code=422)
        return _error_page(request, 422)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception) -> Response:
        logger.exception("unhandled error on %s", request.url.path)
        return _error_page(request, 500)

    return app
