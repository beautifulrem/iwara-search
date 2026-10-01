# Contributing

## Setup

```bash
uv sync                 # runtime + dev tools (ruff, mypy, pytest, pre-commit)
uv run pre-commit install
make help               # list common tasks
```

## Workflow

| Task | Command |
|---|---|
| Format & autofix | `make fmt` |
| Lint | `make lint` (ruff format --check + ruff check) |
| Types | `make typecheck` (mypy `--strict`, app + deployment manager) |
| JS types | `make jscheck` (`tsc --checkJs` over `static/*.js`, JSDoc types) |
| Fast tests + coverage gate (95 %) | `make cov` (parallel, includes Hypothesis property tests) |
| Performance budgets (200k movies) | `make perf` |
| Browser E2E + axe accessibility | `make e2e` (CI: Chromium, Firefox, WebKit) |
| Dev server with reload | `make serve` |

CI (`.github/workflows/ci.yml`) runs all of the above plus `pip-audit`, `shellcheck` and a
Docker build with a container health check. Pull requests must be green.

## Conventions

* **Layers**: `web` → `storage` → `models`; `services` → `crawler`/`parsers`/`storage`.
  Storage returns typed dataclasses, never dicts; presentation formatting lives in Jinja filters.
* **Schema changes** are new functions appended to `storage/migrations.py::MIGRATIONS`. Never
  edit a released migration. Add a test that upgrades from the previous version.
* **SQL**: bind every value; interpolate only identifiers from the whitelists in `storage/sql.py`.
  New query shapes need an index and, if hot, a budget in `tests/test_performance.py`.
* **Scraped URLs** must pass `utils.safe_url` in the parser; templates render them through `safe_href`.
* **Crawler politeness** defaults are part of the product. Don't raise the default rate or
  concurrency, and keep robots.txt handling on.
* **UI**: no inline scripts, styles or event handlers (CSP), every string goes through
  `tr()` with the key present in *all* `locales/*.toml` (enforced by tests), WCAG 2.2 AA
  (enforced by axe in `tests/e2e`).
* **Parser changes**: refresh `tests/fixtures/*.html` from the live site (strip scripts/styles)
  so the snapshot tests track the real markup.

## Releases

1. Update `CHANGELOG.md` and the version in `pyproject.toml` and `search_iwara/__init__.py`.
2. `uv lock`, `make check perf e2e`.
3. Tag `vX.Y.Z` and push.
