# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities privately through [GitHub Security Advisories](https://github.com/beautifulrem/iwara-search/security/advisories/new) rather than opening a public issue. Include affected versions and minimal reproduction steps. Reports receive an initial response within 7 days.

## Supported Versions

Security fixes are released on the latest minor/patch version on `main`.

## Security Boundaries

- **Read-only web tier**: Request handlers open SQLite connections with `PRAGMA query_only` and never execute DDL or writes after startup migrations complete.
- **URL allow-listing & XSS prevention**: Scraped links are restricted to `https` on `oreno3d.com` and `iwara.tv` at parse time, cleaned in existing databases via migrations, and validated again at render time (`safe_href`). Jinja2 auto-escaping is enabled globally, and `Content-Security-Policy` blocks inline scripts, inline styles, and framing.
- **Bounded input & parameterised SQL**: Query parameters enforce strict length, range, and list-size limits (`422` on violation), and all SQL values use bound parameters.
- **Supply-chain & runtime hardening**: GitHub Actions are pinned to commit SHAs, Docker base images are pinned by SHA-256 digest, release artifacts carry SLSA build provenance attestations, and `systemd` / Docker Compose deployments run under unprivileged accounts with read-only filesystems and dropped capabilities (see [docs/linux-deploy.md](docs/linux-deploy.md#security-hardening)).
