# Progress Log (`PROGRESS`)

Chronological engineering log of baselines, experiments, milestones, adversarial review findings, and verifications.

---

## 2026-11-25 — Phase 0–5: Baseline, Research, Independent Audit & Architecture Decisions

- **Environment & Baseline**:
  - Verified hardware/runtime: Linux 6.18.57 x86_64 (`2 vCPU` Intel Xeon @ 2.30GHz, `7.8 GiB` RAM, SQLite `3.53.1`, Node `v22.23.5`, Docker `29.10.0`).
  - Synced to `origin/main` `97fb04d` (`v0.2.2` + Dependabot & pytest 9.2 updates). All baseline checks pass (`303` unit/property tests at `95.89%` coverage, `20` slow tests, `52` Chromium E2E tests, `0` `pip-audit` advisories, baseline Docker image `275.26 MB`).
- **200,000-Movie Baseline Benchmark (`baseline_metrics.json`)**:
  - Uncovered four major database/memory bottlenecks: `search_tag_all_and_not` = `261.3 ms` P50 (`2,136.9 ms` 16-thread P95); `GET /authors` = `134.4 ms` P50 (`243.9 ms` P95); `detail_related_movies` = `41.1 ms` P50 (full 200k scan of `idx_movies_hot`); `migrate` peak RSS = `2,705.4 MB` with `327.42 MB` DB size (`192.55 MB` FTS alone).
- **FTS5 Empirical Storage Experiment (5,000 docs, SQLite `3.53.1`)**:
  - Verified `contentless_delete=1` is incompatible with `columnsize=0` (`OperationalError`), whereas `content='', contentless_delete=1` (+ `detail=none` on `movie_search_short`) passes all `MATCH`, `DELETE`, `optimize`, and `integrity-check` operations while shrinking FTS disk usage by **55.4%** (`2.96 MiB` → `1.32 MiB`).
- **Independent `frontend-reviewer` Subagent Audit**:
  - Ran isolated Principal Product Designer subagent over 29 live Chromium screenshots across desktop, tablet, mobile, dark/light, `zh-Hans`/`ja`/`en`, keyboard, and No-JS. Verdict: *Design direction sound; Conditional Pass pending 5 `P1` UX fixes* (`AUD-007`–`AUD-011`) plus `P2` input/detail/responsive refinements (`AUD-013`).
- **Architecture Decisions Recorded**:
  - [ADR-0001](../adr/0001-modular-monolith-ssr.md): Retain Python + FastAPI + Jinja2 SSR + Progressive Vanilla JS modular monolith.
  - [ADR-0002](../adr/0002-sqlite-dual-fts5-read-models.md): Dual SQLite FTS5 (`contentless_delete=1`) + precomputed read models & v5 query optimizations.
  - [ADR-0003](../adr/0003-polite-single-writer-sync-and-compliance.md): Polite single-writer crawler, validated redirect/size guards & `suppressed` compliance tombstones.
