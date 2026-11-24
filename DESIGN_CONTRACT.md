# Design Contract (`DESIGN_CONTRACT.md`)

## 1. Product Positioning & Target Users
- **Product:** `Search Iwara` — a private, self-hosted, local-first boolean search, faceted filter, and archival metadata discovery index for Oreno3D / Iwara 3D & MMD works (`SQLite FTS5` + `FastAPI` + `Jinja2` + progressive-enhancement Vanilla JS/CSS). Indexes public metadata only; never downloads, hosts, or plays video files.
- **Target Users:**
  1. **3D / MMD Collectors & High-Frequency Boolean Searchers (`zh-Hans` / `ja` / `en`):** Power users scanning hundreds of multi-script works who need rapid 1-click inclusion (`ALL` / `ANY`) and exclusion (`NOT`) across characters, tags, authors, and origins, plus date/popularity thresholds and archived metadata access for removed upstream works.
  2. **Self-Hosted Instance Operators:** Technical users who need immediate visibility into sync freshness and corpus size, zero-JS resilience, strict CSP compliance, and sub-50ms query speed.

## 2. Evolution Objectives & Selected Design Direction
- **Selected Direction:** **Refined Concept A — "Persistent Facet Workbench & Stage Contact Sheet"** (incorporating all mandatory fixes from `Review Type: Concept`).
- **Product Character & Visual World:** `exact, archival, nocturnal` — a **3D Render Light-Table & Faceted Archive Workbench**. Neutral low-chroma slate-graphite surfaces (`hue 265`, chroma `≤ 0.012`), crisp 1px hairlines, architectural radii (`4px / 6px / 8px / 12px`—eliminating `999px` pill overload, decorative gradients, colored glows, dashed empty boxes, playful `-6deg` logo tilts, and `-3px` card hover floats), `tabular-nums` monospace telemetry, and a single solid **Stage Ruby** accent (`hue 356`) paired with semantic **Require Emerald/Teal (`ALL`)** and **Exclude Vermilion (`NOT`)** boolean chips.

## 3. Core User Workflows & Interaction Architecture
1. **1-Click Boolean Facet Workbench (`/` Search Surface):**
   - **DOM Order for Keyboard Efficiency:** `<main id="main">` precedes `<aside class="sidebar">` in HTML so pressing `Tab` from `#site-search` reaches sort/filter controls and the first result card immediately (reducing Tab stops from **45** to **≤ 12**), while CSS Grid (`grid-template-areas: "sidebar main"`) places the `260px` workbench rail on the left on desktop (`≥ 64rem`).
   - **Quick Range Presets:** Calendar-aligned date window toggles (`近 7 天 / 7d`, `近 30 天 / 30d`, `近 90 天 / 90d` mapped to `YYYY-MM-DD` `published_from`) and threshold toggles (`浏览 ≥ 1K`, `点赞 ≥ 100`), idempotently removable on second click.
   - **4 Core Entity Facet Sections (`角色`, `标签`, `作者`, `原作`, Top 6 each from cached `entity_stats`, labeled honestly as corpus-wide counts):**
     - Clicking the entity name performs a clean solo pivot (`/?author_any=11`, `/?tag_any=31`).
     - Dedicated **`+` (Include)** and **`−` (Exclude)** operator links beside every row (`≥ 24×24px` desktop, `≥ 44×44px` coarse pointer, `≥ 4px` gap, localized `aria-label`s):
       - Tag `+` toggles **`tag_all`** (marking active if in `tag_all` or `tag_any`, removing from both on toggle-off, and stripping from `tag_not`); Character/Author/Origin `+` toggles **`*_any`** (stripping from `*_not`).
       - All 4 dimensions' `−` toggles **`*_not`** (simultaneously stripping from `*_any` and `tag_all` to prevent contradictory zero-result traps).
   - **Dataset Sync Telemetry Card:** Placed in the facet workbench rail (and preserved in `<footer>`), showing corpus count (`已收录 N 部`) and sync freshness (`更新于 ...`), keeping the header right area clean for interactive Language & Theme controls.
2. **Zero-Drop Advanced Filter Sheet (`dialog#filters`) & No-JS Resilience (`[P0-1]` Fix):**
   - Removes desktop `backdrop-filter: blur()` so users can inspect live results while adjusting filters.
   - Surfaces **Quick Range Presets (`7d / 30d / 90d / 浏览 ≥ 1K / 点赞 ≥ 100`, JST-anchored)** at the top of `dialog#filters` for 1-tap mobile access (`≥ 44×44px` coarse targets), keeps hidden `<input type="hidden" name="q">` plus compact `ALL / ANY` keyword mode selector, and keeps `dialog#drawer` focused on fast Global Navigation.
   - **No-JS & Half-Typed Input Guarantee:** Every combobox text `<input>` carries a fallback `name` (`q_author_any`, `q_tag_all`, etc.) resolved server-side against entity names when non-empty (and canonicalized out of pagination/canonical links); with JS enabled, submitting the form resolves any pending combobox input and strips all empty/default parameters so the resulting URL matches `SearchFilters.to_query_dict()` with zero `?author_any=&tag_not=&...` URL pollution.
   - Autocomplete popup (`?counts=1` opt-in query param on `/api/{kind}`) displays right-aligned `tabular-nums` corpus counts without breaking default `/api/{kind}` JSON schema (`[{"id": ..., "name": ...}]`).
3. **Structured Boolean Query Strip (`[P2-1]` Fix):**
   - Every active refinement renders as a semantic removable chip distinguishing `ALL` (required intersection), `ANY` (union inclusion), `NOT` (exclusion with strikethrough), `OR` keyword mode (`title_mode=any`), and clean mathematical range bounds (`≥ 500`, `≤ 50,000`, `500 – 50,000`—never `500 – …`).
   - Filter button badge count equals `len(active_filters)` (exact number of active chips).
   - Header search box displays a subtle scoped indicator + 1-click "Clear query" button when active filters or query text exist.
4. **Context-Preserving Movie Detail & Honest Archival States (`[P1-1]`, `[P1-2]`, `[P2-2]` Fixes):**
   - Keeps `/movies/{id}` card URLs clean while preserving search return context via validated same-origin `Referer` on the server (factored into `movie_detail` ETag material, zero-JS compatible) paired with `sessionStorage` persistence in `app.js` across reloads/language switches, promoted to the top breadcrumb/back bar.
   - Detail page removes the redundant global `<aside>` sidebar, using the full container width with balanced 2-column desktop proportions (eliminating the 220px dead black hole), de-cardified inline telemetry (`浏览 · 点赞 · 发布于 · 同步时间`), hairline taxonomy rows with direct browse + `+`/`−` filter links, and no fake centered embedded-video `▶` button.
   - When `movie.status == "missing"`, the media frame displays an explicit archival slate (`源站已下架 · 仅保留归档元数据`) with zero play icons, and external links use secondary/ghost archival button styling instead of a glowing primary "Watch" CTA.
5. **Dedicated Full-Width Entity Rankings (`/characters`, `/authors`, `/tags`, `/origins`, `/categories`) (`[P1-6]` Fix):**
   - Removes the duplicate global `<aside>` sidebar on all ranking routes.
   - Adds a unified 5-tab Directory Switcher (`角色 · 作者 · 标签 · 原作 · 热门分类`) at the top of ranking pages so `/categories` is first-class and navigable, plus visible sorting metrics (`综合热度 = 浏览 + 点赞×50`, showing `作品数 · 总点赞 · 总浏览` in aligned `tabular-nums` columns so rank order is 100% transparent).
   - On `/authors`, removes redundant author-name repetition inside that author's own work rail and fixes `.rail` horizontal inset padding (eliminating `edge-flush-cards`).

## 4. Must-Preserve Capabilities & Non-Goals
- **Must Preserve:** All routes (`/`, `/movies/{id}`, `/characters`, `/authors`, `/tags`, `/origins`, `/categories`, `/api/{kind}`, `/healthz`, `/readyz`, `/metrics`, `/robots.txt`, `/sitemap*.xml`), all URL query parameter names, strict CSP (`no unsafe-inline`, no inline `style=` or `on*=`, no external font CDNs), trilingual catalogs (`zh-Hans`, `ja`, `en` key parity), `favicon.svg` diamond-loupe prism mark, SVG sprite icon system (`icons.svg`), WAI-ARIA 1.2 comboboxes, `/` shortcut, `light-dark()` + `@supports not` token parity, `prefers-reduced-motion` (intentional non-jarring state transitions), `forced-colors`, and `print` styles.
- **Non-Goals:** No embedded video playback, no fake video durations/avatars/ratings, no user accounts or server-side saved state, no heavy frontend JS framework or build bundler.

## 5. Measurable Acceptance Criteria & Hard Gates
1. **Keyboard Efficiency:** On `/`, pressing `Tab` from `#site-search` reaches the sort/filter toolbar in **≤ 6 Tab presses** and the first result card in **≤ 12 Tab presses** (down from 45).
2. **Facet Click Reduction:** Adding or excluding any top entity or applying a date/view/like preset on desktop `/` requires **1 click** (down from 6).
3. **Mobile Above-the-Fold Budget:** On `390×844` mobile `/` (unfiltered), sticky header height is **≤ 58px** (down from `117px`) and the first video card starts at **`y ≤ 185px`** (unfiltered) and **`y ≤ 250px`** (with 2 active filter chips, down from `394px`), with mobile cards displaying compact 1-line un-sliced tags.
4. **Zero Glyph Slicing:** `.tag` and `.card__author` render clean CSS `text-overflow: ellipsis` on block/inline-block inner spans across all widths with zero mid-character clipping.
5. **Contrast & Target Size Gate:**
   - Every text token pair meets **≥ 4.5:1** contrast and every interactive border/focus token (`--border-strong`, `--focus`) meets **≥ 3.0:1** against both `--bg` and `--surface` in **both Light and Dark** themes.
   - All interactive controls on desktop meet **≥ 24×24 CSS px** (`≥ 44×44 CSS px` on `@media (pointer: coarse)`), with **0 `axe-core` violations** across all 7 routes × 2 viewports × 2 themes + open dialogs.
6. **Zero-JS & Clean URL Gate:** Submitting entity text in `dialog#filters` with JavaScript disabled filters results accurately instead of dropping input; submitting with JavaScript enabled emits zero empty query parameters.
7. **Deterministic Anti-Slop & Engineering Gate:**
   - `impeccable detect` reports **0 errors and 0 warnings** across source files and live rendered routes (`/`, `/movies/900000`, `/authors`, `/categories`, `/missing-page`).
   - `make check` (`ruff`, `mypy --strict`, `tsc --checkJs`, pytest coverage `≥ 95%`), `pytest -m e2e`, and `pytest -m slow` (200k-movie performance budgets) **100% PASS**.
   - Final independent `frontend-reviewer` evaluation in a fresh context achieves **weighted score ≥ 8.0 / 10**, **0 open P0/P1 issues**, and verdict **`PASS`**.
