---
name: Search Iwara
description: Precision boolean search, faceted workbench, and archival contact-sheet index for 3D / MMD metadata.
colors:
  stage-ruby: "light-dark(oklch(51.5% 0.205 356), oklch(72.5% 0.165 356))"
  stage-ruby-strong: "light-dark(oklch(46% 0.195 356), oklch(78.5% 0.14 356))"
  stage-ruby-ink: "light-dark(oklch(46.5% 0.195 356), oklch(81% 0.12 356))"
  stage-ruby-soft: "light-dark(oklch(95.4% 0.024 356), oklch(28% 0.065 356))"
  on-stage-ruby: "light-dark(oklch(100% 0 0), oklch(16% 0.025 356))"
  require-teal: "light-dark(oklch(45% 0.125 175), oklch(80% 0.12 175))"
  require-teal-soft: "light-dark(oklch(95.2% 0.03 175), oklch(27% 0.045 175))"
  exclude-vermilion: "light-dark(oklch(49% 0.18 26), oklch(77.5% 0.13 26))"
  exclude-vermilion-soft: "light-dark(oklch(95.4% 0.024 26), oklch(28% 0.055 26))"
  status-emerald: "light-dark(oklch(47.5% 0.125 155), oklch(79.5% 0.125 155))"
  status-emerald-soft: "light-dark(oklch(95.4% 0.032 155), oklch(27% 0.045 155))"
  canvas-bg: "light-dark(oklch(98.2% 0.004 265), oklch(15.5% 0.007 265))"
  surface-1: "light-dark(oklch(100% 0 0), oklch(19.5% 0.009 265))"
  surface-2: "light-dark(oklch(96% 0.006 265), oklch(23.2% 0.01 265))"
  surface-3: "light-dark(oklch(92.8% 0.008 265), oklch(27.5% 0.012 265))"
  hairline: "light-dark(oklch(89.5% 0.008 265), oklch(29% 0.011 265))"
  control-border: "light-dark(oklch(58% 0.015 265), oklch(58.5% 0.014 265))"
  ink-primary: "light-dark(oklch(20% 0.016 265), oklch(95.5% 0.005 265))"
  ink-secondary: "light-dark(oklch(36% 0.015 265), oklch(81.5% 0.009 265))"
  ink-muted: "light-dark(oklch(46.5% 0.015 265), oklch(73.5% 0.011 265))"
  card-scrim: "oklch(0% 0 0 / 0.58)"
  pill-scrim: "oklch(10% 0.008 265 / 0.78)"
typography:
  display:
    fontFamily: "\"Inter\", ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", \"PingFang SC\", \"Hiragino Sans\", \"Noto Sans CJK SC\", \"Noto Sans JP\", sans-serif"
    fontSize: "clamp(1.75rem, 1.4rem + 1.5vw, 2.5rem)"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "\"Inter\", ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", \"PingFang SC\", \"Hiragino Sans\", \"Noto Sans CJK SC\", \"Noto Sans JP\", sans-serif"
    fontSize: "clamp(1.125rem, 1.05rem + 0.35vw, 1.375rem)"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  subheadline:
    fontFamily: "\"Inter\", ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", \"PingFang SC\", \"Hiragino Sans\", \"Noto Sans CJK SC\", \"Noto Sans JP\", sans-serif"
    fontSize: "1.25rem"
    fontWeight: 650
    lineHeight: 1.25
  title:
    fontFamily: "\"Inter\", ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", \"PingFang SC\", \"Hiragino Sans\", \"Noto Sans CJK SC\", \"Noto Sans JP\", sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "\"Inter\", ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", \"PingFang SC\", \"Hiragino Sans\", \"Noto Sans CJK SC\", \"Noto Sans JP\", sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "ui-monospace, \"SF Mono\", \"JetBrains Mono\", Menlo, Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
    fontFeature: "\"tnum\" 1"
rounded:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "10px"
  xl: "14px"
spacing:
  1: "0.25rem"
  2: "0.5rem"
  3: "0.75rem"
  4: "1rem"
  5: "1.25rem"
  6: "1.5rem"
  7: "2rem"
  8: "2.5rem"
  9: "3rem"
  10: "4rem"
components:
  button-primary:
    backgroundColor: "{colors.stage-ruby}"
    textColor: "{colors.on-stage-ruby}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.stage-ruby-strong}"
  button-secondary:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "40px"
  chip-require:
    backgroundColor: "{colors.require-teal-soft}"
    textColor: "{colors.require-teal}"
    rounded: "{rounded.sm}"
    padding: "0 10px"
    height: "28px"
  chip-include:
    backgroundColor: "{colors.stage-ruby-soft}"
    textColor: "{colors.stage-ruby-ink}"
    rounded: "{rounded.sm}"
    padding: "0 10px"
    height: "28px"
  chip-exclude:
    backgroundColor: "{colors.exclude-vermilion-soft}"
    textColor: "{colors.exclude-vermilion}"
    rounded: "{rounded.sm}"
    padding: "0 10px"
    height: "28px"
  media-card:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.lg}"
    padding: "8px"
---

# Design System: Search Iwara

## Overview

**Creative North Star: "The Stage Light-Table & Faceted Archive"**

Search Iwara is a precision boolean catalog and archival metadata index for 3D / MMD character animation works—an Operate-mode working tool used in long, multi-script (`zh-Hans` / `ja` / `en`) browsing and filtering sessions. Its visual system treats the screen like a calibrated darkroom contact sheet (and an archival daylight contact table in light mode): interface chrome stays low-chroma, flat, and structurally quiet so 16:9 stage renders and dense CJK/Latin metadata carry 100% of the visual signal.

Every pixel serves either **visual scanning** or **boolean narrowing**. Instead of decorative SaaS tropes—hue-to-hue gradient text, glowing pink pill buttons, rounded gradient icon tiles, rainbow progress meters, or hovering bouncy cards—product character comes from surgical boolean clarity (`ALL` intersection, `ANY` union, `NOT` exclusion) and honest archival states (`active` vs `missing`).

**Key Characteristics:**
- **Low-Chroma Slate-Obsidian & Archival Paper Grounds:** Cool slate neutrals (`hue 265`, chroma `≤ 0.015`) keep multi-hour sessions calm in both nocturnal dark mode and crisp daylight mode.
- **Semantic Boolean Color Coding:** Color outside thumbnails always encodes query logic—Stage Ruby for `ANY` / primary selection, Require Teal for `ALL` intersection, and Exclude Vermilion (with strikethrough) for `NOT` exclusions.
- **Architectural Geometry (`4px–14px`):** Nested rectangular radii replace bubbly `999px` pills across inputs, buttons, chips, and cards.
- **DOM-First Keyboard & Zero-JS Ergonomics:** Main results precede auxiliary rails in DOM order, while every core facet and filter degrades cleanly to standard server-rendered HTML links and forms.

## Colors

A disciplined single-source `light-dark()` OKLCH system paired with an exact `@supports not` mirror for older engines, engineered so every text pair exceeds `6.2:1` and every interactive boundary exceeds `3.8:1`.

### Primary
- **Stage Ruby** (`--accent`, light `oklch(51.5% 0.205 356)` / dark `oklch(72.5% 0.165 356)`): Marks primary actions, active `ANY` union filter chips (`--accent-soft` / `--accent-ink`), active focus indicators (`--focus`), and active facet `+` toggles.

### Secondary
- **Require Teal** (`--require`, light `oklch(45% 0.125 175)` / dark `oklch(80% 0.12 175)`): Reserved exclusively for `ALL` required tag intersections (`tag_all`) so users immediately distinguish intersection narrowing from `ANY` union filters.

### Tertiary
- **Exclude Vermilion** (`--negative`, light `oklch(49% 0.18 26)` / dark `oklch(77.5% 0.13 26)`): Marks `NOT` boolean exclusions (`*_not`, paired with strikethrough text) and `status='missing'` upstream-removal notices.
- **Status Emerald** (`--success`, light `oklch(47.5% 0.125 155)` / dark `oklch(79.5% 0.125 155)`): Marks `status='active'` availability indicators and clipboard copy confirmation.

### Neutral
- **Canvas Ground & Elevated Surfaces** (`--bg`, `--surface`, `--surface-2`, `--surface-3`): Four stepped slate neutrals (`hue 265`) separating page ground, card/panel planes, quiet tags/inputs, and active segmented tabs without heavy drop shadows.
- **Hairline & Control Border** (`--border`, `--border-strong`): Quiet `1px` structural dividers (`--border`) paired with WCAG 1.4.11 `≥ 3.8:1` interactive control outlines (`--border-strong`).
- **Primary, Secondary & Muted Ink** (`--text`, `--text-2`, `--text-muted`): Three explicit text hierarchy tiers, all verified at `≥ 6.2:1` contrast against both ground and card surfaces.

### Named Rules
**The Zero-Gradient Chrome Rule.** Never apply multi-hue gradients or colored glow shadows to text, buttons, section icon tiles, or ranking meters; thumbnails own chromatic richness while chrome uses solid tokens.
**The Boolean Color Meaning Rule.** Ruby (`ANY`), Teal (`ALL`), and Vermilion (`NOT`) carry strict query-logic semantics and must never be used as random decorative highlights.

## Typography

**Display & Body Font:** `"Inter"` paired with locale-ordered CJK system sans stacks (`"PingFang SC"`, `"Noto Sans CJK SC"` for `zh-Hans`; `"Hiragino Sans"`, `"Noto Sans JP"` prioritized via `:root:lang(ja)` for Japanese).
**Label & Telemetry Font:** `"JetBrains Mono"` / `ui-monospace` with `font-variant-numeric: tabular-nums`.

**Character:** Calm, legible multi-script sans typography tuned for dense Japanese brackets (`【MMD】`), Chinese character names, and English render tags, anchored by crisp monospace numerals for counts, ranks, and JST timestamps.

### Hierarchy
- **Display** (`600`, `clamp(1.75rem, 1.4rem + 1.5vw, 2.5rem)`, `1.15`): Error status numerals and standalone onboarding focal titles; never `800–900` weight or gradient-clipped.
- **Headline** (`600`, `clamp(1.125rem, 1.05rem + 0.35vw, 1.375rem)`, `1.25`): Page `h1` titles (search scope heading, movie detail title, ranking directory title).
- **Title** (`600`, `0.9375rem`, `1.4`): Two-line clamped movie card headings (`-webkit-line-clamp: 2`) and section headers.
- **Body** (`400`, `0.9375rem`, `1.6`): Author notes (`65–72ch` max measure), descriptions, and combobox options.
- **Label / Telemetry** (`500`, `0.75rem`, `1.4`, `tabular-nums`): Boolean operator prefixes (`ALL`, `ANY`, `NOT`), view/like pills, corpus counts, keycaps, and timestamps.

### Named Rules
**The Inner-Block Ellipsis Rule.** Never place `text-overflow: ellipsis` directly on a `flex` or `inline-flex` box; always apply truncation to an inner `display: block` child with `min-inline-size: 0` so CJK and Latin glyphs never clip mid-character.

## Layout

- **Container & Workbench Grid:** Max container width `92rem` (`1472px`) with fluid inline padding `clamp(0.75rem, 2.2vw, 2rem)`. On desktop `/` (`≥ 64rem`) when the database is populated, `.layout--with-sidebar` uses `grid-template-columns: 16.25rem minmax(0, 1fr)` and `grid-template-areas: "sidebar main"` while `<main>` sits **first** in HTML DOM order for immediate keyboard access.
- **Dedicated Full-Width Surfaces:** Movie Detail (`/movies/{id}`), Ranking pages (`/characters`, `/authors`, `/tags`, `/origins`, `/categories`), Empty-Database onboarding, and Error pages omit the left `<aside>` rail so their primary content uses the full container width without duplicate side-by-side lists.
- **Mobile First-Viewport Budget (`≤ 39.99rem`):** Compact single-row sticky header (`≤ 56px`), inline title + result count row, and single-row nowrap sort/filter bar keep total unfiltered above-the-fold chrome under `185px` on `390×844` phones, displaying a 2-column card grid with preserved 1-line tags.

## Elevation & Depth

Surfaces are flat by default and rely on **tonal surface steps + `1px` hairlines** (`--border`) rather than ambient card shadows or hover levitation. Shadows appear only on genuinely floating overlays (dropdown menus, combobox popups, and slide-over `<dialog>` sheets), and desktop filter sheets never blur the underlying results grid so users can read results while refining filters.

### Shadow Vocabulary
- **Floating Popover** (`var(--shadow-md)`): Language menu and autocomplete listbox popups.
- **Modal Sheet** (`var(--shadow-xl)`): Slide-over filter sheet (`dialog#filters`) and mobile navigation drawer (`dialog#drawer`).

### Named Rules
**The Grounded Contact-Sheet Rule.** Media cards stay anchored on their grid plane (`translate: none` on hover); hover feedback uses border contrast (`--border-strong`) and title color rather than lifting or tilting cards.

## Shapes

Architectural nested-radius scale replacing generic full-pill (`999px`) controls:
- **Micro (`4px`, `--radius-xs`):** Boolean operator badges, keyboard shortcut keycaps (`/`), card tags, and `+`/`−` facet micro-buttons.
- **Small (`6px`, `--radius-sm`):** Active filter chips, segmented sort items, and preset toggles.
- **Medium (`8px`, `--radius-md`):** Search inputs, buttons, `<select>` controls, and inner card thumbnails (`10px` outer card − `8px` padding ≈ `6px–8px` inner frame).
- **Large (`10px`, `--radius-lg`):** Media cards, ranking rows, and filter groups.
- **Sheet (`14px`, `--radius-xl`):** Dialog sheet corners and detail stage frame.

## Components

### Buttons & Controls
- **Shape & Sizing:** `8px` radius (`--radius-md`), `40px` (`2.5rem`) standard height (`44px` on `@media (pointer: coarse)`), `600` weight, solid fills without colored drop-shadows.
- **Variants:** Primary (`--accent` fill, `--on-accent` ink), Secondary (`--surface` fill, `1px solid var(--border-strong)`), Ghost (transparent, hover `--surface-2`).

### Boolean Query Chips & Facet Workbench Rows
- **Query Chips (`.filter-chip`):** `6px` radius, `28px` min-height (`36px` coarse), leading monospace operator tag (`ALL` teal, `ANY` ruby, `NOT` vermilion with strikethrough value, or range symbol `≥`/`≤`), value label, and `×` removal affordance.
- **Facet Workbench Rows (`.facet-row`):** `32px` min-height (`44px` coarse) with clickable solo-pivot name, right-aligned `tabular-nums` corpus count, and paired `+` (`≥ 24×24px`) / `−` (`≥ 24×24px`) toggle links separated by `4px` gap.

### Media Contact Cards (`.card`)
- **Structure:** `10px` outer radius, `1px solid var(--border)`, `8px` frame padding around a `6px`-radius `16:9` `.media-frame` thumbnail, high-contrast translucent bottom-right view/like badges (`oklch(10% 0.008 265 / 0.78)`), 2-line balanced/clamped title, single-line block-truncated author + tabular relative time, and 1-line block-truncated tags with `+N` overflow count.

### Comboboxes & Filter Sheet (`dialog#filters`)
- **Behavior:** Native `<dialog>` anchored to right edge on desktop (no backdrop blur) and bottom sheet on mobile; opens with Quick Range Presets + compact `ALL`/`ANY` keyword match mode + expandable WAI-ARIA 1.2 entity comboboxes (`?counts=1` corpus counts in suggestions) + server-side `q_*` fallback resolution for No-JS and unconfirmed text submissions.

### Detail Metadata & Archival Notice
- **Active vs Missing:** Inline tabular telemetry strip (`浏览 · 点赞 · 发布于 · 同步于`), hairline taxonomy table with solo-pivot + `+`/`−` actions, and zero centered fake play buttons. When `status='missing'`, renders an archival slate and secondary source links instead of a primary Watch CTA.

## Do's and Don'ts

### Do:
- **Do** keep `<main id="main">` before `<aside class="sidebar">` in DOM order and position the desktop workbench rail via CSS Grid (`grid-template-areas`).
- **Do** mirror every `light-dark(...)` color token 1:1 in `@supports not (color: light-dark(#000, #fff))` and maintain `≥ 4.5:1` text contrast and `≥ 3.0:1` control-border contrast in both themes.
- **Do** wrap truncated tag and author labels in an inner `display: block` span with `overflow: hidden; text-overflow: ellipsis; white-space: nowrap` and provide `title` attributes when truncated.
- **Do** enforce `≥ 24×24px` desktop target sizes (`≥ 44×44px` on `@media (pointer: coarse)`) on all `+`/`−` facet operators, chip removals, and header tools.

### Don't:
- **Don't** use `background-clip: text` gradients, gradient section icon tiles, rainbow `<meter>` bars, colored button glows, `-6deg` logo rotations, or `-3px` card hover floats.
- **Don't** render a centered `▶` play button over static thumbnails or show a primary "Watch on Iwara" CTA on `status='missing'` archived records.
- **Don't** render the global `<aside>` rail on Movie Detail, Ranking pages, Error pages, or Empty-Database onboarding.
- **Don't** emit inline `style=` attributes, inline `<script>` tags, inline `on*=` handlers, or external font CDN requests (`googleapis`), preserving strict CSP compliance.
