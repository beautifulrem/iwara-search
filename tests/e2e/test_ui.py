"""Browser end-to-end and accessibility tests (Playwright + axe-core).

Run with ``make e2e`` (installs the ``e2e`` dependency group and Chromium).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("axe_playwright_python")

from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Browser, ConsoleMessage, Page, expect

from tests.e2e.conftest import hermetic, wait_ready

pytestmark = pytest.mark.e2e

DESKTOP = {"width": 1440, "height": 900}
MOBILE = {"width": 390, "height": 844}
AXE_PAGES = [
    "/",
    "/?q=yelan&tag_not=32&min_views=10",
    "/movies/200",
    "/authors",
    "/tags",
    "/categories",
    "/missing-page",
]


@pytest.fixture
def console_errors(page: Page, app_url: str) -> list[str]:
    errors: list[str] = []

    def record(message: ConsoleMessage) -> None:
        source = message.location.get("url", "") if message.location else ""
        if message.type == "error" and source.startswith(app_url) and "404" not in message.text:
            errors.append(message.text)

    page.on("console", record)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return errors


def open_page(browser: Browser, app_url: str, path: str, *, viewport: dict[str, int], scheme: str) -> Page:
    context = browser.new_context(viewport=viewport, color_scheme=scheme)  # type: ignore[arg-type]
    hermetic(context, app_url)
    page = context.new_page()
    page.goto(app_url + path)
    wait_ready(page)
    return page


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("viewport", [DESKTOP, MOBILE], ids=["desktop", "mobile"])
@pytest.mark.parametrize("path", AXE_PAGES)
def test_axe_has_no_violations(
    browser: Browser, app_url: str, path: str, viewport: dict[str, int], scheme: str
) -> None:
    page = open_page(browser, app_url, path, viewport=viewport, scheme=scheme)
    page.set_default_timeout(90_000)  # axe on a loaded CI runner can be slow; never flaky
    results = Axe().run(
        page, options={"runOnly": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]}
    )
    assert results.violations_count == 0, results.generate_report()
    page.context.close()


def test_filter_dialog_is_accessible_and_scanned_by_axe(browser: Browser, app_url: str) -> None:
    page = open_page(browser, app_url, "/", viewport=MOBILE, scheme="dark")
    trigger = page.locator('[data-dialog-open="filters"]')
    trigger.click()
    dialog = page.locator("dialog#filters")
    expect(dialog).to_be_visible()
    expect(trigger).to_have_attribute("aria-expanded", "true")
    results = Axe().run(page)
    assert results.violations_count == 0, results.generate_report()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(trigger).to_have_attribute("aria-expanded", "false")
    expect(trigger).to_be_focused()
    page.context.close()


def goto(page: Page, url: str) -> None:
    page.goto(url)
    wait_ready(page)


def test_autocomplete_is_keyboard_operable(page: Page, app_url: str, console_errors: list[str]) -> None:
    goto(page, app_url + "/")
    page.locator('[data-dialog-open="filters"]').first.click()
    group = page.locator("dialog#filters details").filter(has=page.locator("[role=combobox]")).first
    group.locator("summary").click()  # groups without selections start collapsed
    combo = group.locator("[role=combobox]").first
    combo.scroll_into_view_if_needed()
    combo.focus()
    combo.type("Author", delay=20)
    listbox_id = combo.get_attribute("aria-controls")
    expect(page.locator(f"#{listbox_id} [role=option]").first).to_be_visible()
    expect(combo).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("ArrowDown")
    assert combo.get_attribute("aria-activedescendant")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    assert page.url.rstrip("/") == app_url  # Enter selected, it did not submit the form
    chip = page.locator("dialog#filters .chip").first
    expect(chip).to_contain_text("Author")
    page.keyboard.press("Escape")
    assert console_errors == []


def test_mobile_drawer_is_not_hidden_behind_header(browser: Browser, app_url: str) -> None:
    page = open_page(browser, app_url, "/", viewport=MOBILE, scheme="light")
    page.locator('[data-dialog-open="drawer"]').click()
    drawer = page.locator("dialog#drawer")
    expect(drawer).to_be_visible()
    page.wait_for_function(
        "() => document.getElementById('drawer').getAnimations({subtree: true})"
        ".every(a => a.playState !== 'running')"
    )
    first_link = drawer.locator("a").first
    expect(first_link).to_be_in_viewport()
    header_box = page.locator("header").first.bounding_box()
    link_box = first_link.bounding_box()
    assert header_box is not None
    assert link_box is not None
    top_element = page.evaluate(
        "([x, y]) => document.elementFromPoint(x, y)?.closest('dialog')?.id",
        [link_box["x"] + 5, link_box["y"] + link_box["height"] / 2],
    )
    assert top_element == "drawer"  # the drawer, not the sticky header, is on top
    page.keyboard.press("Escape")
    expect(drawer).to_be_hidden()
    page.context.close()


def test_theme_toggle_cycles_and_persists(page: Page, app_url: str) -> None:
    goto(page, app_url + "/")
    toggle = page.locator("[data-theme-toggle]").first
    html = page.locator("html")
    seen = []
    for _ in range(3):
        toggle.click()
        seen.append(html.get_attribute("data-theme-pref"))
    assert seen == ["dark", "light", "system"]
    toggle.click()
    page.reload()
    expect(html).to_have_attribute("data-theme", "dark")


def test_slash_focuses_search_and_sort_menu_navigates(page: Page, app_url: str) -> None:
    goto(page, app_url + "/")
    page.keyboard.press("/")
    expect(page.locator("#site-search")).to_be_focused()
    page.keyboard.press("Escape")
    page.locator("#sort-select").select_option("views_asc")
    page.wait_for_url("**sort=views_asc**")
    expect(page.locator("#sort-select")).to_have_value("views_asc")


def test_active_filter_chip_removes_filter(page: Page, app_url: str) -> None:
    goto(page, app_url + "/?q=yelan&tag_not=32")
    page.locator(".active-filters a", has_text="Tag Beta").click()
    page.wait_for_url(lambda url: "tag_not" not in url)
    assert "q=yelan" in page.url


def test_pagination_and_detail_navigation(page: Page, app_url: str, console_errors: list[str]) -> None:
    goto(page, app_url + "/?page=2")
    expect(page.locator('[aria-current="page"]').filter(has_text="2").first).to_be_visible()
    page.locator("main article .card__title a").nth(1).click()
    page.wait_for_url("**/movies/**")
    expect(page.locator("h1")).to_be_visible()
    assert console_errors == []


def test_works_without_javascript(browser: Browser, app_url: str) -> None:
    context = browser.new_context(java_script_enabled=False)
    hermetic(context, app_url)
    page = context.new_page()
    page.goto(app_url + "/?q=yelan")
    expect(page.get_by_text("sunrise yelan mix")).to_be_visible()
    page.goto(app_url + "/movies/200")
    expect(page.locator("h1")).to_contain_text("sunrise yelan mix")
    context.close()


def test_screenshots_for_review(browser: Browser, app_url: str, tmp_path: Path) -> None:
    """Not an assertion: leaves screenshots under test-results/ for visual review in CI."""

    out = Path("test-results/screens")
    out.mkdir(parents=True, exist_ok=True)
    for name, path in (("home", "/"), ("detail", "/movies/200"), ("authors", "/authors")):
        for vp_name, viewport in (("desktop", DESKTOP), ("mobile", MOBILE)):
            for scheme in ("light", "dark"):
                page = open_page(browser, app_url, path, viewport=viewport, scheme=scheme)
                page.screenshot(path=str(out / f"{name}-{vp_name}-{scheme}.png"), full_page=True)
                page.context.close()


def test_filters_work_without_javascript(browser: Browser, app_url: str) -> None:
    context = browser.new_context(java_script_enabled=False)
    hermetic(context, app_url)
    page = context.new_page()
    page.goto(app_url + "/")
    field = page.locator("#filter-published_from")
    if not field.is_visible():
        page.locator("details", has=field).locator("summary").click()
    expect(field).to_be_visible()
    field.fill("2026-04-12")
    field.press("Enter")
    page.wait_for_url("**published_from=2026-04-12**")
    expect(page.get_by_text("キヴォトス").first).to_be_visible()
    expect(page.get_by_text("sunrise yelan mix")).to_have_count(0)

    # Entity name filtering also works without JavaScript and redirects to clean resolved URL
    page.goto(app_url + "/")
    author_field = page.locator("#f-author_any")
    if not author_field.is_visible():
        page.locator("details", has=author_field).locator("summary").click()
    expect(author_field).to_be_visible()
    author_field.fill("Author Twelve")
    page.locator('dialog#filters button[type="submit"]').click()
    page.wait_for_url(f"{app_url}/?author_any=12")
    assert page.url == f"{app_url}/?author_any=12"
    expect(page.get_by_text("キヴォトス").first).to_be_visible()
    expect(page.get_by_text("sunrise yelan mix")).to_have_count(0)

    # Second sequential No-JS submit preserves existing author_any=12 hidden input
    date_field = page.locator("#filter-published_from")
    if not date_field.is_visible():
        page.locator("details", has=date_field).locator("summary").click()
    date_field.fill("2026-04-12")
    page.locator('dialog#filters button[type="submit"]').click()
    page.wait_for_url("**published_from=2026-04-12**")
    assert "author_any=12" in page.url
    assert "EntityLink" not in page.url
    context.close()


def test_js_filter_form_emits_clean_url_and_resolves_typed_entity(page: Page, app_url: str) -> None:
    goto(page, app_url + "/")
    page.locator('[data-dialog-open="filters"]').first.click()
    group = page.locator("dialog#filters details").filter(has=page.locator("#f-author_any")).first
    group.locator("summary").click()
    combo = page.locator("#f-author_any")
    combo.fill("Author Eleven")
    listbox_id = combo.get_attribute("aria-controls")
    expect(page.locator(f"#{listbox_id} [role=option]").first).to_be_visible()
    # Submit directly without ArrowDown/Enter: JS auto-resolves exact match and strips empty params
    page.locator('dialog#filters button[type="submit"]').click()
    page.wait_for_url(f"{app_url}/?author_any=11")
    assert page.url == f"{app_url}/?author_any=11"


def test_keyboard_tab_budget_and_mobile_fold_budget(browser: Browser, app_url: str) -> None:
    desktop = open_page(browser, app_url, "/", viewport=DESKTOP, scheme="dark")
    desktop.locator("#site-search").focus()
    toolbar_tabs = 0
    card_tabs = 0
    for step in range(1, 15):
        desktop.keyboard.press("Tab")
        where = desktop.evaluate(
            """() => {
                const el = document.activeElement;
                if (!el) return "";
                if (el.closest(".toolbar")) return "toolbar";
                if (el.closest(".card")) return "card";
                return el.tagName;
            }"""
        )
        if where == "toolbar" and not toolbar_tabs:
            toolbar_tabs = step
        if where == "card" and not card_tabs:
            card_tabs = step
            break
    assert 1 <= toolbar_tabs <= 6, f"Expected toolbar within 6 Tabs, got {toolbar_tabs}"
    assert 1 <= card_tabs <= 12, f"Expected first card within 12 Tabs, got {card_tabs}"
    desktop.context.close()

    mobile = open_page(browser, app_url, "/", viewport=MOBILE, scheme="dark")
    header_box = mobile.locator(".site-header").bounding_box()
    first_card_box = mobile.locator("main .card").first.bounding_box()
    assert header_box is not None
    assert header_box["height"] <= 58, header_box
    assert first_card_box is not None
    assert first_card_box["y"] <= 185, first_card_box
    mobile.context.close()


def test_detail_back_search_and_taxonomy_preserve_query_context(page: Page, app_url: str) -> None:
    goto(page, app_url + "/?q=yelan&min_views=500")
    page.locator("main .card__title a").first.click()
    page.wait_for_url("**/movies/**")
    back = page.locator("[data-back-search]")
    expect(back).to_be_visible()
    exc_op = page.locator('.tax-chip__op--exc[data-tax-kind="tags"]').first
    expect(exc_op).to_be_visible()
    exc_op.click()
    page.wait_for_url("**tag_not=**")
    assert "q=yelan" in page.url
    assert "min_views=500" in page.url

    # Navigating to an independent directory (/authors) clears stale sessionStorage search context
    goto(page, app_url + "/authors")
    page.locator(".author-row .card__title a").first.click()
    page.wait_for_url("**/movies/**")
    expect(page.locator("[data-back-search]")).to_have_attribute("href", "/")
    author_inc = page.locator('.tax-chip__op--inc[data-tax-kind="authors"]').first
    inc_href = author_inc.get_attribute("href")
    assert inc_href is not None
    assert "q=" not in inc_href


def test_filter_sheet_single_keyword_sync_and_unclipped_combobox(page: Page, app_url: str) -> None:
    goto(page, app_url + "/")
    # Fill header search without submitting yet, then open filter sheet (single keyword authority)
    page.locator("#site-search").fill("yelan")
    page.locator('[data-dialog-open="filters"]').first.click()
    expect(page.locator("#filter-q")).to_have_count(0)

    # Bottom combobox (#f-tag_not) opens upward (.is-dropup) without jump-scrolling .sheet__body
    tag_group = page.locator("dialog#filters details").filter(has=page.locator("#f-tag_not")).first
    if not page.locator("#f-tag_not").is_visible():
        tag_group.locator("summary").click()
    body_el = page.locator("dialog#filters .sheet__body")
    combo = page.locator("#f-tag_not")
    combo.scroll_into_view_if_needed()
    scroll_before = body_el.evaluate("el => el.scrollTop")
    combo.click()
    popup = page.locator("dialog#filters .combo").filter(has=combo).locator(".combo__popup")
    expect(popup).to_be_visible()
    expect(popup).to_have_class(re.compile(r"\bis-dropup\b"))
    scroll_after = body_el.evaluate("el => el.scrollTop")
    assert abs(scroll_after - scroll_before) <= 1, (scroll_before, scroll_after)
    combo_box = combo.bounding_box()
    popup_box = popup.bounding_box()
    body_box = body_el.bounding_box()
    foot_box = page.locator("dialog#filters .sheet__foot").bounding_box()
    assert combo_box is not None
    assert popup_box is not None
    assert body_box is not None
    assert foot_box is not None
    assert popup_box["y"] >= body_box["y"] - 1, (popup_box, body_box)
    assert popup_box["y"] + popup_box["height"] <= combo_box["y"] + 1, (combo_box, popup_box)
    assert popup_box["y"] + popup_box["height"] <= foot_box["y"] + 1, (popup_box, foot_box)

    metrics_badge = page.locator('dialog#filters details[data-fgroup="metrics"] [data-fgroup-badge]')
    expect(metrics_badge).to_be_hidden()
    preset = page.locator('dialog#filters .preset-chip[data-preset-field="min_views"]')
    preset.click()
    assert page.url.rstrip("/") == app_url  # toggled in-place, did not discard form state
    expect(preset).to_have_attribute("aria-current", "true")
    expect(page.locator("#filter-min_views")).to_have_value("1000")
    expect(metrics_badge).to_be_visible()
    expect(metrics_badge).to_have_text("1")
    page.locator('dialog#filters button[type="submit"]').click()
    page.wait_for_url("**min_views=1000**")
    assert "q=yelan" in page.url


def _assert_all_targets(page: Page, min_px: float, scope: str = "body") -> None:
    violations = page.evaluate(
        """({ minPx, scope }) => {
            const root = document.querySelector(scope) || document.body;
            const sel = 'a[href]:not([tabindex="-1"]), button, input:not([type="hidden"]), select, summary';
            const bad = [];
            for (const el of root.querySelectorAll(sel)) {
                if (el.closest('[hidden], dialog:not([open]), details:not([open]) > :not(summary), .sr-only')) continue;
                const st = getComputedStyle(el);
                if (st.display === 'none' || st.visibility === 'hidden') continue;
                const r = el.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) continue;
                if (r.width < minPx || r.height < minPx) {
                    bad.push({
                        tag: el.tagName,
                        cls: el.className,
                        text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 24),
                        w: Math.round(r.width * 10) / 10,
                        h: Math.round(r.height * 10) / 10,
                    });
                }
            }
            return bad;
        }""",
        {"minPx": min_px, "scope": scope},
    )
    assert violations == [], violations


def test_mobile_detail_and_ranking_layout_and_coarse_targets(browser: Browser, app_url: str) -> None:
    context = browser.new_context(viewport=MOBILE, color_scheme="dark", has_touch=True, is_mobile=True)
    hermetic(context, app_url)
    page = context.new_page()

    # Home: coarse targets >= 44x44px, brand mark visible, clear-all on-screen, zero horizontal page overflow
    page.goto(app_url + "/?q=yelan&tag_all=31&tag_not=32&author_any=11&min_views=10")
    wait_ready(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    header_box = page.locator(".site-header").bounding_box()
    brand_box = page.locator(".site-header .brand").bounding_box()
    first_card_box = page.locator("main .card").first.bounding_box()
    clear_box = page.locator(".active-filters__clear").bounding_box()
    assert header_box is not None
    assert header_box["height"] <= 58
    assert brand_box is not None
    assert brand_box["width"] >= 43.5
    assert first_card_box is not None
    assert first_card_box["y"] <= 250
    assert clear_box is not None
    assert clear_box["x"] + clear_box["width"] <= 390, clear_box
    expect(page.locator(".search__scope")).to_be_hidden()
    expect(page.locator(".toolbar .segmented")).to_be_hidden()
    expect(page.locator("#sort-select option")).to_have_count(8)

    # Verify short card tags (MMD, 60fps, etc.) and +N badges are never crushed or sliced on 390px/360px
    tag_clips = page.evaluate(
        """() => {
            const out = [];
            for (const el of document.querySelectorAll('.card__tags .tag__text, .card__tags .tag--more')) {
                if (el.offsetParent === null) continue;
                const txt = el.textContent.trim();
                if ((txt.length <= 6 || txt.startsWith('+')) && el.scrollWidth > el.clientWidth + 1) {
                    out.push({ txt, clientW: el.clientWidth, scrollW: el.scrollWidth });
                }
            }
            return out;
        }"""
    )
    assert tag_clips == [], tag_clips

    visible_text_w = page.locator("#site-search").evaluate(
        """el => {
            const st = getComputedStyle(el);
            return el.getBoundingClientRect().width - parseFloat(st.paddingLeft) - parseFloat(st.paddingRight);
        }"""
    )
    assert visible_text_w >= 165, visible_text_w
    _assert_all_targets(page, 43.5)

    # Even on 360px narrow mobile in English with 4 active chips, zero docScrollWidth overflow
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(app_url + "/?lang=en&q=yelan&tag_all=31&tag_not=32&author_any=11&min_views=10")
    wait_ready(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    sort_box = page.locator("#sort-select").bounding_box()
    ft_metrics = page.locator(".toolbar .filter-trigger").evaluate(
        """el => {
            const r = el.getBoundingClientRect();
            return { right: r.right, clientW: el.clientWidth, scrollW: el.scrollWidth };
        }"""
    )
    assert sort_box is not None
    assert sort_box["width"] >= 180, sort_box
    assert ft_metrics["scrollW"] <= ft_metrics["clientW"] + 1, ft_metrics
    assert ft_metrics["right"] <= 360, ft_metrics
    page.set_viewport_size(MOBILE)
    page.goto(app_url + "/?q=yelan&tag_all=31&min_views=10")
    wait_ready(page)

    # Mobile filter sheet: upward (.is-dropup) unclipped bottom combobox popup without jump-scroll + >= 44x44px
    page.locator(".toolbar .filter-trigger").click()
    expect(page.locator("dialog#filters")).to_be_visible()
    tag_group = page.locator("dialog#filters details").filter(has=page.locator("#f-tag_not")).first
    if not page.locator("#f-tag_not").is_visible():
        tag_group.locator("summary").click()
    m_body = page.locator("dialog#filters .sheet__body")
    m_combo = page.locator("#f-tag_not")
    m_combo.scroll_into_view_if_needed()
    m_scroll_before = m_body.evaluate("el => el.scrollTop")
    m_combo.click()
    popup = page.locator("dialog#filters .combo").filter(has=m_combo).locator(".combo__popup")
    expect(popup).to_be_visible()
    m_scroll_after = m_body.evaluate("el => el.scrollTop")
    assert abs(m_scroll_after - m_scroll_before) <= 1, (m_scroll_before, m_scroll_after)
    m_combo_box = m_combo.bounding_box()
    m_popup_box = popup.bounding_box()
    m_body_box = m_body.bounding_box()
    m_foot_box = page.locator("dialog#filters .sheet__foot").bounding_box()
    assert m_combo_box is not None
    assert m_popup_box is not None
    assert m_body_box is not None
    assert m_foot_box is not None
    assert m_popup_box["y"] >= m_body_box["y"] - 1, (m_popup_box, m_body_box)
    assert m_popup_box["y"] + m_popup_box["height"] <= m_foot_box["y"] + 1, (m_popup_box, m_foot_box)
    is_dropup = popup.evaluate("el => el.classList.contains('is-dropup')")
    if is_dropup:
        assert m_popup_box["y"] + m_popup_box["height"] <= m_combo_box["y"] + 1, (m_combo_box, m_popup_box)
    else:
        assert m_popup_box["y"] >= m_combo_box["y"] + m_combo_box["height"] - 1, (m_combo_box, m_popup_box)
    _assert_all_targets(page, 43.5, "dialog#filters")
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")

    # Mobile navigation drawer: language + theme controls accessible, >= 44x44px, and unclipped in Japanese
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(app_url + "/?lang=ja")
    wait_ready(page)
    page.locator(".site-header__menu").click()
    expect(page.locator("dialog#drawer")).to_be_visible()
    expect(page.locator("dialog#drawer .drawer__lang").first).to_be_visible()
    expect(page.locator("dialog#drawer .drawer__theme")).to_be_visible()
    drawer_w = page.locator("dialog#drawer").evaluate(
        "el => ({ clientW: el.clientWidth, scrollW: el.scrollWidth })"
    )
    assert drawer_w["scrollW"] <= drawer_w["clientW"] + 1, drawer_w
    _assert_all_targets(page, 43.5, "dialog#drawer")
    page.keyboard.press("Escape")
    page.set_viewport_size(MOBILE)

    # Detail: h1 title and primary Watch CTA appear ABOVE author comment on mobile; zero horizontal overflow
    page.goto(app_url + "/movies/200")
    wait_ready(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator("[data-back-search]")).to_be_hidden()
    h1_box = page.locator("h1.detail__title").bounding_box()
    cta_box = page.locator(".detail__actions .btn").first.bounding_box()
    comment_box = page.locator(".detail__comment").bounding_box()
    assert h1_box is not None
    assert cta_box is not None
    assert comment_box is not None
    assert h1_box["y"] < cta_box["y"] < comment_box["y"]
    headings = page.locator("main :is(h1, h2, h3)").evaluate_all("els => els.map(e => e.tagName)")
    assert headings[0] == "H1"
    _assert_all_targets(page, 43.5)

    # Rankings (/tags & /authors): 2-row compact mobile layout & zero horizontal overflow on /authors
    page.goto(app_url + "/authors")
    wait_ready(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.goto(app_url + "/tags")
    wait_ready(page)
    table_box = page.locator(".rank-table").bounding_box()
    row = page.locator(".rank-row").first
    badge_box = row.locator(".rank-badge").bounding_box()
    works_box = row.locator(".rank-row__works").bounding_box()
    fav_box = row.locator(".rank-row__fav").bounding_box()
    views_box = row.locator(".rank-row__views").bounding_box()
    expect(row.locator(".rank-row__unit")).to_be_visible()
    assert table_box is not None
    assert badge_box is not None
    assert works_box is not None
    assert fav_box is not None
    assert views_box is not None
    assert works_box["x"] > badge_box["x"] + badge_box["width"]
    assert views_box["x"] + views_box["width"] <= table_box["x"] + table_box["width"]
    _assert_all_targets(page, 43.5)
    context.close()

    # Coarse tablet (>= 64rem): site-nav links, sidebar workbench operators (>=4px gap) & more links >= 44x44px
    tablet = browser.new_context(viewport={"width": 1060, "height": 800}, color_scheme="dark", has_touch=True)
    hermetic(tablet, app_url)
    t_page = tablet.new_page()
    t_page.goto(app_url + "/")
    wait_ready(t_page)
    _assert_all_targets(t_page, 43.5)
    op_gap = t_page.locator(".wb-row__ops").first.evaluate(
        """el => {
            const [a, b] = el.querySelectorAll('.wb-op');
            return b.getBoundingClientRect().left - a.getBoundingClientRect().right;
        }"""
    )
    assert op_gap >= 3.5, op_gap
    tablet.close()

    # Fine desktop: all interactive controls >= 24x24px; /tags, /categories, and /authors hide duplicate dir-tabs & never overflow
    fine_page = open_page(browser, app_url, "/", viewport=DESKTOP, scheme="dark")
    _assert_all_targets(fine_page, 23.5)
    fine_page.goto(app_url + "/authors")
    wait_ready(fine_page)
    assert fine_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    author_cta = fine_page.locator(".author-row__head .btn").first.bounding_box()
    assert author_cta is not None
    assert author_cta["x"] + author_cta["width"] <= 1440, author_cta
    fine_page.goto(app_url + "/categories")
    wait_ready(fine_page)
    expect(fine_page.locator(".dir-tabs")).to_be_hidden()
    fine_page.goto(app_url + "/tags")
    wait_ready(fine_page)
    expect(fine_page.locator(".dir-tabs")).to_be_hidden()
    head_box = fine_page.locator(".page-head").bounding_box()
    toolbar_box = fine_page.locator(".dir-toolbar").bounding_box()
    assert head_box is not None
    assert toolbar_box is not None
    assert abs((head_box["y"] + head_box["height"]) - (toolbar_box["y"] + toolbar_box["height"])) <= 24
    _assert_all_targets(fine_page, 23.5)
    fine_page.context.close()

    # No-JS mobile exposes top-of-page directory navigation in a compact 2-row header (<= 104px)
    nojs = browser.new_context(viewport={"width": 360, "height": 800}, java_script_enabled=False)
    hermetic(nojs, app_url)
    nojs_page = nojs.new_page()
    nojs_page.goto(app_url + "/")
    expect(nojs_page.locator(".site-nav a").first).to_be_visible()
    nojs_header = nojs_page.locator(".site-header").bounding_box()
    assert nojs_header is not None
    assert nojs_header["height"] <= 104, nojs_header
    nojs.close()


def test_filter_sheet_preserves_existing_entities_without_422(page: Page, app_url: str) -> None:
    goto(page, app_url + "/?tag_all=31,32&author_any=11")
    # Also seed 8 selected chips in DOM to ensure >= 7 entities never exceed IdList max_length=240
    page.evaluate(
        """() => {
            const combo = document.querySelector('#f-tag_not')?.closest('[data-combobox]');
            const chips = combo?.querySelector('[data-combo-chips]');
            const hidden = combo?.querySelector('[data-combo-value]');
            if (!chips || !hidden) return;
            const ids = ['101', '102', '103', '104', '105', '106', '107', '108'];
            hidden.value = ids.join(',');
        }"""
    )
    page.locator('[data-dialog-open="filters"]').first.click()
    preset = page.locator('dialog#filters .preset-chip[data-preset-field="min_views"]')
    preset.click()
    page.locator('dialog#filters button[type="submit"]').click()
    page.wait_for_url("**min_views=1000**")
    assert "EntityLink" not in page.url
    assert "author_any=11" in page.url
    assert "tag_all=31%2C32" in page.url
    expect(page.locator(".error-page")).to_have_count(0)


def test_empty_db_mobile_onboarding_axe_and_untruncated_command(browser: Browser, empty_app_url: str) -> None:
    for scheme in ("light", "dark"):
        page = open_page(browser, empty_app_url, "/?lang=en", viewport=MOBILE, scheme=scheme)
        cmd_metrics = page.locator("#sync-command").evaluate(
            "el => ({ clientW: el.clientWidth, scrollW: el.scrollWidth })"
        )
        assert cmd_metrics["scrollW"] <= cmd_metrics["clientW"] + 1, cmd_metrics
        results = Axe().run(
            page,
            options={"runOnly": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]},
        )
        assert results.violations_count == 0, results.generate_report()
        page.context.close()
