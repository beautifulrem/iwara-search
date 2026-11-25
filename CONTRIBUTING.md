# Contributing

## Local Setup

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and Node.js 22+ (for `tsc --checkJs` over browser scripts).

```bash
uv sync
uv run pre-commit install
make help
```

## Verification Commands

| Task | Command |
|---|---|
| Format & autofix | `make fmt` |
| Lint (`ruff format --check` + `ruff check`) | `make lint` |
| Python static types (`mypy --strict`) | `make typecheck` |
| Browser JS types (`tsc --checkJs`) | `make jscheck` |
| Unit, integration & property tests (`>= 95%` coverage) | `make cov` |
| 200k-movie query & refresh latency budgets | `make perf` |
| Playwright E2E + `axe-core` WCAG 2.2 AA | `make e2e` |
| Local dev server with auto-reload (`:8765`) | `make serve` |

`.github/workflows/ci.yml` runs all of the above (with E2E across Chromium, Firefox, and WebKit), plus `pip-audit`, `shellcheck`, Prometheus `promtool` rule tests, and a Docker build + `/readyz` smoke check.

## Codebase Conventions

- **Layer boundaries**: `web` -> `storage` -> `models`, and `services` -> `crawler` / `parsers` / `storage`. Storage returns typed dataclasses rather than raw dicts; presentation helpers live in `search_iwara/web/formatting.py`.
- **Database migrations**: Append new schema changes to `MIGRATIONS` in `search_iwara/storage/migrations.py`. Never mutate an already-shipped migration, and add an upgrade test from the prior schema version.
- **SQL safety & indexing**: Bind all user values as parameters; interpolate only whitelisted column/table identifiers in `search_iwara/storage/sql.py`. Every new query shape must use an index, and hot paths belong in `tests/test_performance.py`.
- **External URLs**: Every scraped URL must pass `utils.safe_url` during parsing, and templates render external links through `safe_href`.
- **Crawler defaults**: Keep default concurrency (`4`), rate ceiling (`2.0` req/s), and `robots.txt` enforcement conservative.
- **Frontend & i18n**: Follow [docs/design.md](docs/design.md) and [docs/accessibility.md](docs/accessibility.md). Inline scripts, inline styles, and `on*=` attributes are forbidden by CSP; every UI string must go through `tr()` across all `search_iwara/locales/*.toml` catalogs.
- **Workflow actions**: Pin every GitHub Action in `.github/workflows/*.yml` to a full 40-character commit SHA with its version tag in a trailing comment (`# vX.Y.Z`), enforced by `tests/deploy/test_scripts.py`.

## Cutting a Release

Releases are automated via [`scripts/release.py`](scripts/release.py) and [`.github/workflows/release.yml`](.github/workflows/release.yml):

1. Record user-visible changes under `## [Unreleased]` in `CHANGELOG.md`.
2. Bump versions and stamp `CHANGELOG.md` + `uv.lock`:
   ```bash
   make release VERSION=0.3.0
   ```
3. Run `make check` and merge/push the release commit to `main`.
4. Tag and push:
   ```bash
   git tag v0.3.0
   git push origin v0.3.0
   ```

Pushing `vX.Y.Z` verifies version parity (`tag == pyproject.toml == search_iwara/__init__.py`), runs lint/type/unit/audit checks, builds attested `.whl` + `.tar.gz` + `SHA256SUMS` artifacts, publishes multi-arch (`linux/amd64`, `linux/arm64`) images to `ghcr.io/beautifulrem/iwara-search`, and creates the GitHub Release from `CHANGELOG.md`.
