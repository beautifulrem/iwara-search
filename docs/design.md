# UI Design & Frontend Guide

Search Iwara uses server-rendered Jinja2 templates (`search_iwara/templates/`), layered vanilla CSS (`search_iwara/static/style.css`), and a single progressive-enhancement ES module (`search_iwara/static/app.js`) checked with `tsc --checkJs`. There is no frontend bundler or external CDN dependency.

## Core Principles

1. **Thumbnails carry the colour**: Surfaces stay low-chroma (`saturation <= 0.016` on cool slate `hue ~265`) so 16:9 artwork and titles remain the focal point during long browsing sessions.
2. **Semantic boolean hues**: Colour accents signal filter polarity rather than decoration:
   - **Ruby (`--accent`)**: primary actions, active navigation, and `ANY` inclusions.
   - **Teal (`--require`)**: `ALL` required tag intersections (`tag_all`).
   - **Vermilion (`--exclude`)**: `NOT` exclusions (`*_not`).
   - **Emerald (`--ok`)**: active availability indicators.
3. **Additive facet navigation**: Clicking `+` or `−` beside an entity in the `/` sidebar or on a movie detail page refines the current query instead of wiping active filters.
4. **Progressive enhancement**: Search, sorting, facet refinement, and form submission work with JavaScript disabled. Typed entity names in the no-JS filter form (`q_*` parameters) resolve on the server and redirect (`303`) to canonical ID parameters.

## Colour & Spacing Tokens

Tokens live in `@layer tokens` inside `search_iwara/static/style.css` using CSS `light-dark()` in OKLCH, paired with an exact `@supports not (color: light-dark(black, white))` fallback block verified by unit tests (`tests/test_units.py`).

| Token | Role | Contrast Requirement |
|---|---|---|
| `--bg`, `--surface`, `--surface-2`, `--surface-3` | Page canvas, cards, inputs, hover states | Separation via `--border` hairlines rather than drop shadows |
| `--text`, `--text-2`, `--text-muted` | Primary, secondary, and metadata copy | `>= 4.5:1` against both `--bg` and `--surface` |
| `--border-strong`, `--focus` | Interactive control borders and `:focus-visible` ring | `>= 3.0:1` against adjacent surfaces |
| `--accent`, `--require`, `--exclude` | Action buttons and boolean filter chips | `>= 4.5:1` for chip ink on soft tints |

Radii stay compact (`4px` badges, `6px` controls and chips, `8px–10px` cards, `14px` modal sheets). Avoid pill (`999px`) shapes on standard buttons or inputs, decorative text gradients, and backdrop blur over result grids.

## Typography & Mixed-Script Rules

- **UI & CJK stack**: `"Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", "PingFang SC", "Hiragino Sans", "Noto Sans CJK SC", "Noto Sans JP", sans-serif`.
- **Numeric counters**: View counts, likes, rank positions, IDs, and corpus counts use `font-variant-numeric: tabular-nums` so columns align vertically.
- **Ellipsis safety**: Never place `overflow: hidden; text-overflow: ellipsis` directly on `display: flex` or `inline-flex` elements (which clips CJK glyphs mid-character in Chromium/WebKit). Wrap truncated text inside a dedicated `display: block` child (`<span class="tag__text">`, `<span class="card__author-text">`).
- **Third-party script tagging**: Titles, tags, and comments pass through `lang_attribute()` (`search_iwara/web/formatting.py`), emitting `lang="ja"` when kana is present and `lang="ko"` for Hangul while leaving ambiguous Han-only strings unmarked.

## Layout & DOM Order

- **DOM vs. visual order on `/`**: `<main id="main">` precedes `<aside class="sidebar">` in `base.html` so keyboard `Tab` moves straight from the header search input to the sort bar and result cards. Desktop CSS Grid (`grid-template-areas: "sidebar main"`) places the facet rail visually on the left (`>= 1024px`).
- **Full-width secondary views**: Detail pages (`/movies/{id}`), entity directories (`/characters`, `/authors`, `/tags`, `/origins`, `/categories`), empty-database onboarding, and error pages omit `<aside>` and use the full container width.
- **Mobile budget (`<= 720px`)**: Single-row sticky header (`<= 58px`), compact single-row sort/filter bar, preserved 1-line card tags with `+N` overflow badge, and `>= 44×44px` hit areas under `@media (pointer: coarse)`.
- **Archived upstream records**: When `movie.status == "missing"`, detail pages render a non-interactive archival frame and demote outbound links to secondary styling instead of displaying an active "Watch" call to action.

## Frontend Guardrails

- **Strict CSP**: `script-src 'self'` and `style-src 'self'`. Inline `<script>`, `<style>`, `style="..."`, and `on*="..."` attributes are blocked by browser policy and rejected by `tests/test_web.py`.
- **i18n completeness**: Every user-facing string must use `tr("...")` and exist in all three locale files (`search_iwara/locales/en.toml`, `ja.toml`, `zh-Hans.toml`).
- **Accessibility checks**: Run `make e2e` after template, CSS, or script edits to verify `axe-core` rules, keyboard focus management, combobox ARIA states, and coarse-pointer target sizes.
