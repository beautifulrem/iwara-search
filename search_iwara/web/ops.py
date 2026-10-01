"""Operational endpoints: health checks, Prometheus metrics, robots.txt, sitemaps and favicon."""

from __future__ import annotations

import ipaddress
import secrets
import sqlite3
from typing import Annotated, Final
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ..models import RANKING_KINDS
from ..storage import SCHEMA_VERSION
from .context import StateDep

router = APIRouter(include_in_schema=False)
SITEMAP_CHUNK: Final = 50_000  # protocol limit per sitemap file
XML_MEDIA_TYPE: Final = "application/xml"


@router.api_route("/healthz", methods=["GET", "HEAD"])
def healthz() -> dict[str, str]:
    """Liveness: the process is up and serving."""

    return {"status": "ok"}


@router.api_route("/readyz", methods=["GET", "HEAD"])
def readyz(state: StateDep) -> JSONResponse:
    """Readiness: the database is readable and on the expected schema version."""

    try:
        connection = state.pool.get()
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        connection.execute("SELECT 1 FROM movies LIMIT 1").fetchall()
    except sqlite3.Error as exc:
        return JSONResponse({"status": "unavailable", "error": type(exc).__name__}, status_code=503)
    if version != SCHEMA_VERSION:
        return JSONResponse(
            {"status": "unavailable", "schema": version, "expected": SCHEMA_VERSION}, status_code=503
        )
    return JSONResponse({"status": "ok", "schema": version})


def _is_loopback(host: str | None) -> bool:
    try:
        return host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


@router.get("/metrics")
def metrics(request: Request, state: StateDep) -> Response:
    """Prometheus exposition.

    With ``SEARCH_IWARA_METRICS_TOKEN`` set, a matching ``Authorization: Bearer`` header is
    required; without it only loopback clients are served, so a publicly bound instance
    never leaks metrics by default.
    """

    if not state.settings.metrics_enabled:
        raise HTTPException(status_code=404)
    token = state.settings.metrics_token
    if token:
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied.encode(), f"Bearer {token}".encode()):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Bearer realm="metrics"'})
    elif not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(status_code=404)
    registry = request.app.state.metrics.registry
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request, state: StateDep) -> str:
    if not state.settings.allow_indexing:
        return "User-agent: *\nDisallow: /\n"
    return f"User-agent: *\nDisallow: /api/\nDisallow: /metrics\nSitemap: {request.base_url}sitemap.xml\n"


SITEMAP_NS: Final = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _url_entry(loc: str, lastmod: str | None) -> str:
    modified = f"<lastmod>{xml_escape(lastmod[:10])}</lastmod>" if lastmod else ""
    return f"<url><loc>{xml_escape(loc)}</loc>{modified}</url>"


def _urlset(urls: list[tuple[str, str | None]]) -> str:
    entries = "".join(_url_entry(loc, mod) for loc, mod in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="{SITEMAP_NS}">{entries}</urlset>'


def _require_indexing(state: StateDep) -> None:
    if not state.settings.allow_indexing:
        raise HTTPException(status_code=404)


@router.get("/sitemap.xml")
def sitemap_index(request: Request, state: StateDep) -> Response:
    _require_indexing(state)
    total = int(state.pool.get().execute("SELECT COUNT(*) FROM movies WHERE status = 'active'").fetchone()[0])
    base = str(request.base_url)
    locations = [f"{base}sitemap-pages.xml"]
    locations += [f"{base}sitemap-movies-{n}.xml" for n in range(1, -(-total // SITEMAP_CHUNK) + 1)]
    body = "".join(f"<sitemap><loc>{xml_escape(loc)}</loc></sitemap>" for loc in locations)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="{SITEMAP_NS}">{body}</sitemapindex>'
    return Response(xml, media_type=XML_MEDIA_TYPE)


@router.get("/sitemap-pages.xml")
def sitemap_pages(request: Request, state: StateDep) -> Response:
    _require_indexing(state)
    base = str(request.base_url)
    return Response(
        _urlset([(base, None), *((f"{base}{kind}", None) for kind in RANKING_KINDS)]),
        media_type=XML_MEDIA_TYPE,
    )


@router.get("/sitemap-movies-{chunk}.xml")
def sitemap_movies(
    request: Request, state: StateDep, chunk: Annotated[int, Path(ge=1, le=10_000)]
) -> Response:
    _require_indexing(state)
    rows = (
        state.pool.get()
        .execute(
            "SELECT source_site_id, updated_at FROM movies WHERE status = 'active' "
            "ORDER BY id LIMIT ? OFFSET ?",
            (SITEMAP_CHUNK, (chunk - 1) * SITEMAP_CHUNK),
        )
        .fetchall()
    )
    if not rows:
        raise HTTPException(status_code=404)
    base = str(request.base_url)
    return Response(_urlset([(f"{base}movies/{row[0]}", row[1]) for row in rows]), media_type=XML_MEDIA_TYPE)


@router.get("/favicon.ico")
def favicon() -> RedirectResponse:
    return RedirectResponse("/static/favicon.svg", status_code=301)
