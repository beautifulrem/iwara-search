# ADR-0001: Retain Python + FastAPI + Jinja2 SSR + Progressive Vanilla JS Modular Monolith

- **Status**: Accepted
- **Date**: 2026-11-25

## Context

Search Iwara indexes ~200,000+ Oreno3D/Iwara metadata entries for low-cost single-node self-hosting. We evaluated three architectural options:
1. **Option A (Retain & Harden)**: Python (`>=3.13`, `python:3.15-slim` in container) modular monolith (`crawler`, `parsers`, `storage`, `services`, `web`, `cli`) with FastAPI + Jinja2 SSR, ~600 LOC of `tsc --checkJs`-checked vanilla ES module JS, and tokenized CSS Cascade Layers.
2. **Option B (Go/Rust Rewrite)**: Rewrite backend & crawler into a compiled single binary.
3. **Option C (SPA Frontend Migration)**: Replace Jinja2 SSR with React/Vue/Svelte + JSON/GraphQL API.

## Evidence

On our 2-vCPU / 7.8 GiB Linux baseline with 200,000 movies:
- Warm HTTP + Jinja2 + GZip latency is **`21.4 ms` P50** on `GET /`, **`10.8 ms` P50** on `GET /categories`, and **`3.0 ms` P50** on `GET /api/tags`. All baseline slow endpoints (`GET /authors` `134 ms`, `tag_all` `280 ms`, `/movies/{id}` `53 ms`) were dominated (>80%) by SQLite query execution plans, not Python or template rendering.
- Container image is `275 MB`, runtime dependencies total 10 packages (`0` `pip-audit` vulnerabilities), and progressive `<form method="get">` SSR guarantees zero-JS usability, shareable URLs, and strict CSP (`script-src 'self'; style-src 'self'`).

## Decision

**Adopt Option A.** Reject Go/Rust and SPA rewrites as high-risk churn with negative ROI for single-node self-hosters; direct engineering investment into SQLite query plans, FTS5 storage efficiency, RFC 9309 crawler safety, and SSR/progressive UX ergonomics.

## Consequences

- Preserves acyclic module boundaries, `>=95%` test coverage, zero frontend build toolchain in Docker, and full No-JS progressive enhancement.
