# ADR-0003: Single-Writer Batch Crawler, Redirect Guards, and Takedown Tombstones

- **Status**: Accepted
- **Date**: 2026-11-25

## Context

Search Iwara syncs metadata periodically from `oreno3d.com` via a `systemd` timer or Docker loop while serving concurrent web reads. Key operational concerns are isolating crawl load from web latency, bounding untrusted network responses, and distinguishing upstream removals from local operator takedowns.

## Decision

1. **Separate single-writer sync process**: Guard writes with an advisory `fcntl.flock` (`<db>.sync.lock`) and commit detail updates in 25-movie batches, while `search-iwara serve` opens read-only connections (`PRAGMA query_only = ON`).
2. **Per-hop redirect validation and response size caps**: Disable automatic redirect following in `httpx` and validate every hop (`<= 5` hops) against `https` scheme, the configured `base_url` host allow-list, and RFC 9309 `robots.txt` rules. Stream response bodies with hard byte limits (`2 MiB` for `robots.txt`, `10 MiB` for HTML).
3. **Distinct `missing` vs. `suppressed` states**:
   - Upstream `404`/`410` or placeholder pages set `status = 'missing'`, removing FTS entries while keeping archival metadata visible on `/movies/{id}` and allowing automatic recovery if upstream restores the entry.
   - Local takedown (`search-iwara db suppress <id>...`) sets `status = 'suppressed'`, purges FTS entries, returns `404` on `/movies/{id}`, excludes the entry from rankings and sitemaps, and prevents future syncs from re-importing it unless restored with `db unsuppress`.

## Consequences

- Web worker latency stays isolated from crawl bursts without introducing Redis or Celery, and operator takedowns persist cleanly across full or incremental sync runs.
