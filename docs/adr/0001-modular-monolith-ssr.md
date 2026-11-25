# ADR-0001: Server-Rendered Python Modular Monolith

- **Status**: Accepted
- **Date**: 2026-11-25

## Context

Search Iwara indexes ~200,000+ Oreno3D metadata entries for single-node self-hosting on small Linux VPS instances (`1–2 vCPU`, `1–2 GiB` RAM) or home servers. Three architectural shapes were considered:

1. **Python modular monolith with SSR**: Python 3.13+ (`python:3.15-slim` in Docker), FastAPI + Jinja2 server-rendered HTML, layered CSS, and a single `tsc --checkJs`-verified ES module.
2. **Compiled binary rewrite**: Porting the crawler and web server to Go or Rust.
3. **SPA frontend + JSON API**: Replacing Jinja2 templates with a client-side framework and bundler.

## Decision

Keep the server-rendered Python modular monolith (`crawler`, `parsers`, `storage`, `services`, `web`, `cli`).

On a 200,000-movie database, warm end-to-end HTTP + Jinja2 + GZip latency is `~23 ms` P50 on `GET /`, `~15 ms` P50 on `GET /categories`, and `~5 ms` P50 on `GET /api/tags`. Multi-tag and deep-ranking latencies are dominated (>80%) by SQLite index execution rather than Python or template rendering. Server-rendered `<form method="get">` pages also preserve full usability when JavaScript is disabled, keep every search state as a plain URL, require no frontend build step in Docker, and satisfy a strict `Content-Security-Policy` (`script-src 'self'; style-src 'self'`).

## Consequences

- Acyclic package boundaries (`web` -> `storage` -> `models`; `services` -> `crawler` / `parsers` / `storage`) and strict static typing (`mypy --strict` + `tsc --checkJs`) keep maintenance straightforward.
- Performance optimization focuses on SQLite index layout, FTS5 storage representation, and bounded query plans rather than language or framework rewrites.
