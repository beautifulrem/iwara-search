# Security Policy

## Reporting a vulnerability

Please report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/beautifulrem/iwara-search/security/advisories/new)
rather than public issues. Include steps to reproduce and the affected version. You can expect
an acknowledgement within a week.

## Supported versions

Only the latest release receives fixes.

## Security model

* The web tier is read-only: it opens the database with `PRAGMA query_only` and never runs DDL
  outside start-up migrations.
* All scraped URLs are allow-listed (`https` on `oreno3d.com` / `iwara.tv`) at parse time and
  again at render time; templates are auto-escaped; the CSP forbids inline script and style.
* Every query parameter has a structural limit; SQL values are always bound parameters.
* Deployment runs under a dedicated unprivileged user with systemd sandboxing; see
  [docs/linux-deploy.md](docs/linux-deploy.md#security-hardening).
