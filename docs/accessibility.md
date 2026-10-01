# Accessibility statement

Search Iwara aims to conform to **WCAG 2.2 level AA**. This page describes what is verified
automatically on every change, what must be checked by hand, and the limitations we know about.

## What is verified automatically

| Check | Where | Scope |
|---|---|---|
| axe-core (WCAG 2.0/2.1/2.2 A + AA and best-practice rules) | `tests/e2e/test_ui.py` | 7 pages (search, filtered search, detail, authors, tags, categories, 404) × desktop 1440 px and mobile 390 px × light and dark themes, plus the open filter dialog |
| Keyboard operation | `tests/e2e/test_ui.py` | Filter dialog opens, traps focus, closes with <kbd>Esc</kbd> and returns focus to its trigger; the autocomplete is operable with arrows/<kbd>Enter</kbd>/<kbd>Esc</kbd> without submitting the form; <kbd>/</kbd> focuses search; the mobile drawer sits above the sticky header |
| No-JavaScript use | `tests/e2e/test_ui.py` | Search, filters (inline panel), sorting and all links work with scripting disabled |
| Colour contrast of every design-token pair | computed from the OKLCH tokens in `static/style.css` | text ≥ 4.5:1, large text and UI boundaries (inputs, buttons, focus ring) ≥ 3:1, in both themes |
| Content Security Policy compliance | `tests/test_web.py` | no inline script, style or event handlers |
| Screen-reader semantics of the checklist below | `tests/e2e/test_a11y_semantics.py` | every step's roles, accessible names, states (`aria-expanded`, `aria-selected`, `aria-current`), focus movement and live-region announcements, in the English UI |
| Colour fallback for engines without `light-dark()` | `tests/test_units.py` | the fallback block mirrors every light/dark token exactly |

Automated tools find roughly a third to a half of accessibility problems. **Passing them is
necessary, not sufficient.** The semantics tests assert what a screen reader is *given* for each
checklist step; how NVDA or VoiceOver *speaks* it (verbosity, reading order in practice, voice
switching) can only be judged by a person running the checklist below.

## Design commitments

* Semantic landmarks (`header`, `nav`, `main`, `aside`, `footer`), one `h1` per page, a
  "skip to main content" link, and `lang`/`hreflang` on language links.
* Visible `:focus-visible` outline (2 px, ≥ 3:1) that is never hidden by the sticky header
  (`scroll-padding`), target sizes ≥ 24 × 24 px (44 px on coarse pointers).
* Filters use native `<dialog>` (focus trap, <kbd>Esc</kbd>, inert background) and
  `<details>` groups; the autocomplete follows the WAI-ARIA 1.2 combobox pattern
  (`aria-expanded`, `aria-controls`, `aria-activedescendant`, `listbox`/`option`).
* Status messages go through a polite live region: the suggestion count is announced
  once when the list opens or the count changes (debounced 500 ms), not on every keystroke;
  adding/removing a filter and copying the sync command are announced.
* `aria-current` marks the current page, sort and navigation item; decorative icons are
  `aria-hidden`; cover links duplicate the title link, so they are removed from the tab order.
* `prefers-reduced-motion`, `forced-colors` (Windows High Contrast) and print styles are supported;
  every colour token has a fallback for browsers without `light-dark()`.

## Manual screen-reader checklist (for maintainers)

Run before each release with **NVDA + Firefox** (Windows) and **VoiceOver + Safari** (macOS, iOS):

1. **Search** — Tab to the search field; it is announced as "Search videos, search". Submit;
   the results heading and the result count are read; the card titles are headings.
2. **Filters** — Activate "Filters"; the dialog title is announced and focus is inside. Expand a
   group (`<details>`), type in an author combobox: after a pause the number of suggestions is
   announced once; arrow keys read each option; <kbd>Enter</kbd> adds a chip ("Added …");
   <kbd>Backspace</kbd> in the empty field removes the last chip ("Removed …"). <kbd>Esc</kbd>
   first closes the list, then the dialog, and focus returns to "Filters".
3. **Active filters** — each chip is a link announced as "<group> <value>, remove this filter".
4. **Sorting** — the quick sort links announce the current one; the "More orders" select announces
   its label and value.
5. **Detail page** — breadcrumb landmark, `h1` title, the facts list (views, likes, published date),
   the external links announce "(opens in a new window)".
6. **Theme and language** — the theme button announces the current theme and what it switches to;
   the language menu reads each language in its own language.

### Verification log

| Date | Check | Result |
|---|---|---|
| 2026-10-01 | axe (Chromium, Firefox), keyboard, no-JS and screen-reader semantics suites | pass, 0 violations |
| 2026-10-01 | VoiceOver + Safari 27.0 on macOS 27.0 (26A428), English UI, full manual checklist (steps 1–6) — run by the project owner | pass, no issues found |
| — | NVDA + Firefox (Windows), VoiceOver + Safari on iOS | not yet performed — record the date, versions and findings here when done |

## Known limitations

* **Thumbnails** come from oreno3d.com and carry no description; on the detail page the image `alt`
  is "Thumbnail of <title>", in result grids the image is decorative because the title follows.
* **Third-party text** (titles, tags, names, author notes) is shown as published. When its
  language can be told reliably it is marked for screen readers (WCAG 3.1.2): text containing
  kana gets `lang="ja"`, Hangul `lang="ko"`. Text made only of Han characters may be Chinese or
  Japanese; it is deliberately left unmarked because a wrong `lang` is worse than none, so a
  screen reader may read it with the page language's voice.
* Without JavaScript the entity filters (authors, characters, origins, tags) cannot search by
  name; existing selections are kept, date and number ranges work.
* Relative times ("5 hours ago") are computed on the server and are not refreshed while a page
  stays open.

## Feedback

If something is hard or impossible to use, please open an issue at
<https://github.com/beautifulrem/iwara-search/issues> and describe the page, the assistive
technology and browser you used. Accessibility bugs are treated as release blockers.
