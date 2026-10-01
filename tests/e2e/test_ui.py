"""Browser end-to-end and accessibility tests (Playwright + axe-core).

Run with ``make e2e`` (installs the ``e2e`` dependency group and Chromium).
"""

from __future__ import annotations

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
    context.close()
