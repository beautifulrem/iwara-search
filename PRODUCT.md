# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary — Self-Hosting 3D / MMD Collectors & Power Searchers (CJK + Global):** Enthusiasts and archivists of MMD (MikuMikuDance) and 3D character animation who run a private local metadata index because upstream Oreno3D lacks boolean exclusions (`NOT`), multi-tag intersections (`ALL`), numeric/date bounds, fast CJK substring search, and persistent records for removed videos. *(Inferred from repository architecture, README, and search query model.)*
- **Secondary — Self-Hosted Instance Operators:** Technical users operating `search-iwara` via Docker or systemd on a personal server or workstation who rely on sync freshness visibility, zero-maintenance SQLite storage, and predictable keyboard/no-JS operation. *(Inferred from `deploy/`, `ops.py`, and CLI design.)*

## Product Purpose

Search Iwara provides fast, private, multi-dimensional search, boolean facet filtering, entity leaderboards, and archival metadata lookup over a locally synced SQLite mirror of Oreno3D video metadata—without downloading or hosting any video files. Success means a user can narrow tens or hundreds of thousands of indexed 3D works to the exact video, creator, character, or franchise they want in seconds, verify its metadata, and jump directly to Iwara or Oreno3D.

## Positioning

Unlike upstream Oreno3D (which offers single-entity pages and basic keyword search without exclusions or intersections) or heavyweight media servers (which store and transcode gigabytes of video), Search Iwara is a single-SQLite metadata index engineered around dual FTS5 tables (`trigram` + CJK unigram/bigram `unicode61`) and precomputed `entity_stats`. Every query runs against indexes in milliseconds and serializes cleanly into a shareable URL query string:

- One unified query field matching titles, authors, characters, origins, and tags across Chinese, Japanese, and Latin scripts.
- Full boolean entity filtering: `author_any` / `author_not`, `character_any` / `character_not`, `origin_any` / `origin_not`, and `tag_all` / `tag_any` / `tag_not`.
- Range filtering on publish date (`published_from`..`published_to`), view count (`min_views`..`max_views`), and like count (`min_favorites`..`max_favorites`).
- Eight sort orders including time-decayed trending (`hot_desc`), weighted popularity (`view_count + favorite_count × 50`), likes, views, and publish date (ascending/descending).
- Weighted related-video discovery (IDF-capped at 5% corpus frequency so ubiquitous tags do not pollute recommendations) and archived metadata preservation (`status='missing'`) when upstream videos disappear.

## Operating Context

- **High-frequency discovery & filtering loop:** Users arrive with either a broad exploration goal (checking `Trending` or `Newest` after a sync, or browsing top characters/authors) or a specific retrieval goal (combining a character or franchise with required motion/camera/resolution tags while excluding unwanted tags or creators).
- **Trilingual mixed-script metadata:** Real records mix Japanese brackets (`【MMD】`), Chinese/Japanese character and IP names, English render/motion terms (`4K`, `60fps`, `Ray-MMD`), numeric counters, and JST timestamps (`Asia/Tokyo`).
- **Long-session ergonomics:** Users scan dense grids of 16:9 thumbnails and titles across many pages on desktop (`1280px–1920px+`) and mobile (`390px+`), often in dim/dark environments, pivoting repeatedly from a card or detail view into an author, character, origin, or tag filter.

## Capabilities and Constraints

- **Server-rendered progressive enhancement:** FastAPI + Jinja2 HTML templates (`search_iwara/templates/`) enhanced by a zero-build, type-checked ES module (`search_iwara/static/app.js`, `tsc --checkJs`) and Vanilla CSS (`search_iwara/static/style.css`). Every core search, sort, filter, and navigation flow must remain functional with JavaScript disabled.
- **Strict security & privacy boundary:** Enforces strict `Content-Security-Policy` (`default-src 'self'`, `script-src 'self'`, `style-src 'self'`, `font-src 'self'`, no `unsafe-inline`, no inline `style=` or `on*=` attributes, no third-party font/script CDNs such as `googleapis`). External `href`/`src` values pass strict host allow-lists (`oreno3d.com`, `iwara.tv`) with `referrerpolicy="no-referrer"`.
- **Trilingual parity:** Full UI localization in Simplified Chinese (`zh-Hans`), Japanese (`ja`), and English (`en`) via `search_iwara/locales/*.toml` with identical key sets enforced by automated tests, plus automatic `lang="ja"` / `lang="ko"` tagging on third-party metadata strings where kana or Hangul are detected.
- **Latency & query budget:** Web requests use read-only SQLite connections (`PRAGMA query_only`), capped result counting (`10,000+`), ETag/304 conditional responses, and strict 200k-movie latency budgets (`tests/test_performance.py`).
- **NSFW metadata handling:** Production mirrors index adult content (`noindex, nofollow` by default); documentation, tests, and screenshots use work-safe synthetic catalogs and generated stage thumbnails.

## Brand Commitments

- **Name:** `Search Iwara`
- **Mark:** Faceted diamond-loupe + play prism icon (`search_iwara/static/favicon.svg`, `docs/assets/logo.svg`), referencing low-poly 3D / MMD geometry and search inspection.
- **Disclaimer:** Explicitly non-affiliated local metadata mirror; never claims to host or stream video files.

## Evidence on Hand

- Application templates, CSS, and client scripts: `search_iwara/templates/`, `search_iwara/static/style.css`, `search_iwara/static/app.js`.
- Architecture & accessibility specifications: `docs/architecture.md`, `docs/accessibility.md`, `docs/configuration.md`.
- Synthetic demo & E2E verification suites: `scripts/make_screenshots.py`, `tests/e2e/test_ui.py`, `tests/e2e/test_a11y_semantics.py`, `tests/test_performance.py`.
- Absence to respect: No real user accounts, saved server-side playlists, video playback/streaming, or social commenting exist; the UI must never fabricate fake user profiles, star ratings, video durations (not in schema), or playback progress bars.

## Product Principles

1. **Facet Velocity Over Modal Friction:** Boolean inclusion, exclusion, and pivoting across authors, characters, origins, and tags are the primary reason Search Iwara exists; common facet actions should take minimal clicks and keep active query logic transparent at a glance.
2. **Media & Metadata First, Quiet Chrome:** Thumbnails, multi-script titles, creators, and taxonomy links carry the visual signal; surrounding interface chrome stays calm, structured, and free of decorative gradients or template noise during long browsing sessions.
3. **Honest Archival Precision:** Distinguish local dataset scope, sync recency, capped counts (`10,000+`), missing thumbnails, and removed upstream videos (`missing`) clearly without inventing unavailable metadata.
4. **Universal Resilience:** Keyboard operability, screen-reader semantics, strict CSP compliance, CJK/Latin typographic legibility, and zero-JS fallbacks are first-class product guarantees, never optional polish.

## Accessibility & Inclusion

- Targets **WCAG 2.2 Level AA** across desktop and mobile in both light and dark color schemes, continuously verified by `axe-core` (`tests/e2e/test_ui.py`) and screen-reader semantics tests (`tests/e2e/test_a11y_semantics.py`).
- Requires `≥ 4.5:1` contrast for text and `≥ 3:1` for UI controls/focus indicators across `light-dark()` OKLCH tokens (with exact `@supports not` fallbacks), `≥ 24×24px` (`44px` coarse pointer) targets, full keyboard operation (`/` search shortcut, `<dialog>` focus return, WAI-ARIA 1.2 comboboxes), `prefers-reduced-motion`, `forced-colors`, and `print` stylesheet support.
