# Autonomous Execution Plan (`EXECPLAN`)

See [ROADMAP.md](ROADMAP.md) for strategic context and non-goals, and [AUDIT.md](AUDIT.md) for evidence-backed root causes (`AUD-001`–`AUD-014`).

## Execution Checklist & Acceptance Gates

| Milestone | Scope | Audit IDs Addressed | Automated Gate | Status |
|---|---|---|---|---|
| **M0** | Engineering memory (`docs/evolution/`, `docs/adr/`) & repo bloat cleanup (`design-evidence/`, transient root `DESIGN_*.md`) | `AUD-014` | `ruff`, `pytest -m "not slow and not e2e"` | In Progress |
| **M1** | SQLite Schema v5 (`contentless_delete` FTS, `idx_movies_author_top`, `app_meta['active_movies']`, streamed rebuild), JST `hot_score`, FTS rename/missing consistency, NFKC entity lookup, `tag_all`/page-1/`related_movies` query plans, `db suppress`/`unsuppress`/`reindex`, Hypothesis Search Oracle | `AUD-001`, `AUD-002`, `AUD-003`, `AUD-004`, `AUD-011`, `AUD-012`, `AUD-014` | `mypy`, `pytest`, `pytest -m slow` | Planned |
| **M2** | Crawler 5-hop validated redirects & byte caps, Web HTTP `304`/`HEAD`/`/readyz`/`COOP`/`CORP`/range-swap, Docker `SIGTERM` & immediate sync, Nginx `/static/` headers, webhook URL validation | `AUD-005`, `AUD-006`, `AUD-013`, `AUD-014` | `mypy`, `shellcheck`, `pytest` | Planned |
| **M3** | Dynamic context-preserving Facet Workbench, Directory search/sort & `/authors` disclosure layout, live filter-sheet badges & `.is-dropup` combobox, mobile header/search/clear-all/`60fps` fixes, `author_comment` safe linkification & responsive polish | `AUD-007`, `AUD-008`, `AUD-009`, `AUD-010`, `AUD-013` | `tsc`, `pytest`, `pytest -m e2e` | Planned |
| **M4** | 200k Before/After benchmarks, independent `frontend-reviewer` + `arch-security-db-reviewer` adversarial reviews, screenshot & documentation refresh, full release verification | All (`AUD-001`–`AUD-014`) | All gates (`ruff`, `mypy`, `tsc`, `shellcheck`, `pytest --cov`, `slow`, `e2e`, `pip-audit`, `promtool`, `docker`) | Planned |
