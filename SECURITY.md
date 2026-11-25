# Security Policy

## Reporting a vulnerability

Please report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/beautifulrem/iwara-search/security/advisories/new)
rather than public issues. Include steps to reproduce and the affected version. You can expect
an acknowledgement within a week.

## Supported versions

Only the latest release receives fixes.

## Security model

* **Read-only web tier**: `search-iwara serve` opens SQLite through `ReadOnlyPool` (`PRAGMA query_only = ON`)
  and never runs DDL or writes outside startup schema migrations.
* **Outbound crawler protections**: `Oreno3dClient` validates every request and redirect hop (max 5 hops)
  to `https://` on the configured origin host without URL credentials, re-checks `robots.txt` (RFC 9309)
  on every redirect hop, and enforces streaming response body caps (`10 MiB` HTML, `2 MiB` `robots.txt`).
* **Untrusted content & XSS defence**: all scraped URLs are allow-listed (`https` on `oreno3d.com` /
  `iwara.tv`) at parse time, sanitised by migration, and filtered again at render time (`safe_href`).
  Creator comments are HTML-escaped before linkifying validated `https://` URLs with
  `rel="noopener noreferrer"`. Strict Content-Security-Policy (`script-src 'self'`, `style-src 'self'`,
  `frame-ancestors 'none'`) is enforced on both dynamic responses and `/static/` assets.
* **Input & SQL safety**: every query parameter has structural bounds; all SQL values use parameter binding;
  `LIKE` patterns escape `%`, `_`, and `\`; FTS5 tokens wrap inside escaped double-quoted phrases.
* **Deployment hardening**: systemd units run under an unprivileged user with filesystem/syscall sandboxing,
  and `alert_webhook` requires `https://` (or loopback `http://`), rejects URL credentials, link-local /
  cloud-metadata, unspecified, and multicast IP literals, and refuses HTTP redirects during delivery; see
  [docs/linux-deploy.md](docs/linux-deploy.md#security-hardening).

## Metadata takedowns & local suppression

Search Iwara indexes publicly listed metadata only and hosts **no video files**. Upstream removals
(HTTP `404`/`410`) are automatically transitioned to `status = 'missing'` and purged from full-text
search indexes during sync.

Self-hosted operators handling a rights-holder takedown or local compliance request can permanently
suppress specific `source_site_id` records across future sync runs:

```bash
uv run search-iwara db suppress 123456 789012 --reason "rightsholder request"
```

Suppressed entries return HTTP `404` on `/movies/{id}`, are excluded from all search results, facets,
rankings, related-video recommendations, and sitemaps, and are never re-activated by subsequent
`sync latest` or `sync full` runs unless explicitly restored via `search-iwara db unsuppress <id...>`.
