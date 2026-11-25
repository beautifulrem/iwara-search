# Accessibility

Search Iwara targets **WCAG 2.2 Level AA** across desktop and mobile viewports in both light and dark colour schemes. This document covers automated checks run in CI, manual screen-reader checks for releases, and known constraints of third-party metadata.

## Automated CI Coverage

| Check | Test Location | Scope |
|---|---|---|
| `axe-core` (WCAG 2.0 / 2.1 / 2.2 A + AA + best-practice) | `tests/e2e/test_ui.py` | 7 routes (`/`, filtered `/`, `/movies/200`, `/authors`, `/tags`, `/categories`, `404`) across desktop (`1440×900`) and mobile (`390×844`), light and dark themes, plus the open filter dialog and directory search/sort states; executed in **Chromium, Firefox, and WebKit** |
| Keyboard navigation & focus management | `tests/e2e/test_ui.py` | `<dialog>` focus containment, `Esc` dismissal with focus restoration, WAI-ARIA 1.2 combobox arrow/`Enter`/`Esc` handling (with drop-up positioning near the viewport bottom), `/` search shortcut, skip link, directory `<details>` disclosures, and `<main>`-before-`<aside>` tab order |
| Pointer targets & mobile zoom prevention | `tests/e2e/test_ui.py` | Interactive controls meet `>= 24×24 px` on fine pointers and `>= 44×44 px` (with `>= 16 px` input font size) under `@media (pointer: coarse)` across phone and tablet layouts |
| JavaScript-disabled operation | `tests/e2e/test_ui.py` | Keyword search, inline boolean filter submission (`q_*` server-side name resolution), dynamic facet links, directory search/sort, sorting, and pagination with scripting turned off |
| Design-token contrast | `tests/test_units.py` | Computed from OKLCH tokens in `static/style.css`: body text `>= 4.5:1`, UI boundaries and focus outlines `>= 3.0:1`, plus exact `@supports not (color: light-dark(...))` fallback parity |
| Screen-reader semantics | `tests/e2e/test_a11y_semantics.py` | Landmarks, heading hierarchy, accessible names, `aria-expanded` / `aria-selected` / `aria-current` states, external-link new-tab hints, and live-region announcements |
| Content Security Policy | `tests/test_web.py` | Verifies zero inline scripts, inline styles, or inline DOM event attributes |

Automated checks catch structural and contrast regressions reliably, while real assistive-technology speech order and verbosity still require periodic manual testing.

## Frontend Commitments

- **Landmarks and headings**: Every page exposes `header`, `nav`, `main`, and `footer` (`aside` on `/` when populated), a single `h1`, a visible-on-focus skip link, and `lang`/`hreflang` attributes on locale switchers.
- **Focus visibility**: `2px` `:focus-visible` outlines (`>= 3:1` contrast) with `scroll-padding-top` so sticky headers never obscure focused elements.
- **Native disclosure & dialogs**: Filter sheets use `<dialog>` (`showModal()` focus management and background `inert`); collapsible filter groups and menus use `<details>`/`<summary>` labelled directly through their DOM content (WCAG 2.5.3 Label in Name).
- **Polite live announcements**: Combobox suggestion counts announce after a `500 ms` debounce when opened or changed rather than on every keystroke; adding/removing filter chips and copying CLI commands announce via `aria-live="polite"`.
- **Media preferences**: Supports `prefers-reduced-motion`, `forced-colors` (Windows High Contrast), and `@media print`.

## Manual Screen-Reader Checklist

Run prior to major UI releases with **NVDA + Firefox** (Windows) or **VoiceOver + Safari** (macOS / iOS):

1. **Search**: Press `Tab` to reach the search input, submit a query, and confirm the results heading and count read clearly.
2. **Filter sheet & combobox**: Open **Filters**, expand an entity section, type into a combobox, verify the debounced suggestion count, select an option with arrow keys + `Enter` ("Added ..."), remove a chip with `Backspace` ("Removed ..."), and press `Esc` twice to close suggestions and return focus to **Filters**.
3. **Active filter chips & quick facets**: Verify each active chip reads both its boolean operator/category and value, and that sidebar `+`/`−` buttons announce their entity name and action.
4. **Sorting & directories**: Confirm quick-sort controls indicate the current sort (`aria-current`), the full sort `<select>` announces its label and selected option, and directory search/sort controls preserve focus predictability.
5. **Detail page**: Verify the breadcrumb landmark, `h1` title, metadata list, taxonomy `+`/`−` actions, and "(opens in a new tab)" hint on external links.
6. **Theme & language**: Confirm the theme button announces both current mode and next mode, and the language switcher reads each locale option in its target language.

## Known Limitations

- **Upstream thumbnails**: Oreno3D provides no image descriptions. Result-grid thumbnails are marked decorative because the linked title immediately follows; detail-page thumbnails use `"Thumbnail of <title>"`.
- **Mixed CJK script detection**: Third-party titles, tags, and notes containing hiragana or katakana receive `lang="ja"`, and Hangul strings receive `lang="ko"`. Strings composed solely of shared Han characters are left without an override `lang` attribute rather than guessing between Chinese and Japanese voices.
- **No-JS autocomplete**: With JavaScript disabled, entity inputs do not show live popup suggestions, though submitting typed names resolves against indexed entities on the server.
- **Static relative timestamps**: Relative labels ("3 hours ago") render at request time and update on navigation rather than ticking live in the DOM.

## Reporting Issues

If any workflow is difficult or impossible to operate with assistive technology, please open an issue at <https://github.com/beautifulrem/iwara-search/issues> noting the page URL, browser, and assistive tool.
