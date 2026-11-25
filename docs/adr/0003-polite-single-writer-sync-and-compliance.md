# ADR-0003: Polite Single-Writer Batch Crawler, Redirect/Size Guards & Metadata Takedown Model

- **Status**: Accepted
- **Date**: 2026-11-25

## Context

Search Iwara crawls `oreno3d.com` periodically via `systemd` timer or Docker `sync` loop. We evaluated:
1. Crawler process separation vs in-web-process background tasks or external Redis/Celery queues.
2. HTTP redirect and response body safety under RFC 9309 & OWASP SSRF guidelines.
3. Handling rights-holder/operator takedowns vs transient upstream `404`/`410` removals.

## Decision

1. **Retain Separate Single-Writer Batch Sync Process** (`fcntl.flock` + `CrawlStore` 25-movie transactions): Isolates read-only web workers (`PRAGMA query_only = ON`) from crawl memory/latency without requiring Redis/Celery.
2. **Enforce Validated Redirects & Streaming Byte Caps in `Oreno3dClient`**:
   - Set `follow_redirects=False` and validate every redirect hop (`<= 5` hops per RFC 9309 §2.4) against `http`/`https` scheme, configured `base_url` host allow-list, and `_check_robots()`.
   - Stream HTTP bodies with hard byte ceilings (`2 MiB` for `robots.txt`, `10 MiB` for HTML) to prevent OOM.
3. **Add Persistent `suppressed` Tombstone Status & CLI (`search-iwara db suppress` / `unsuppress`)**:
   - Upstream `404`/`410` sets `status = 'missing'` (purging FTS postings while retaining archival metadata and allowing restoration if upstream recovers).
   - Operator takedown (`search-iwara db suppress <source_site_id>...`) sets `status = 'suppressed'`, purges FTS postings, returns `404` on `/movies/{id}`, excludes the item from search/rankings/sitemaps, and prevents future `sync` runs from re-activating or re-fetching it.
