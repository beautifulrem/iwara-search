"""Screen-reader semantics: the accessibility tree and announcements behind the manual checklist.

Each test mirrors a step of the "Manual screen-reader checklist" in docs/accessibility.md and
asserts what a screen reader is *given* — roles, accessible names, states, focus movement and
live-region text — in the English UI. What these tests cannot judge is how a particular
screen reader *speaks* that information; that part of the checklist stays manual.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import wait_ready

pytestmark = pytest.mark.e2e


def open_en(page: Page, app_url: str, path: str = "/") -> None:
    separator = "&" if "?" in path else "?"
    page.goto(f"{app_url}{path}{separator}lang=en")
    wait_ready(page)


def live_region(page: Page) -> str:
    return page.locator("#live-region").inner_text()


def test_landmarks_headings_and_skip_link(page: Page, app_url: str) -> None:
    open_en(page, app_url)
    for role in ("banner", "search", "navigation", "main", "complementary", "contentinfo"):
        expect(page.get_by_role(role).first).to_be_attached()
    expect(page.get_by_role("heading", level=1)).to_have_count(1)
    page.keyboard.press("Tab")
    skip = page.get_by_role("link", name="Skip to main content")
    expect(skip).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("main#main")).to_be_focused()


def test_checklist_1_search(page: Page, app_url: str) -> None:
    open_en(page, app_url)
    field = page.get_by_role("searchbox", name="Search videos")
    expect(field).to_be_visible()
    field.fill("yelan")
    field.press("Enter")
    page.wait_for_url("**q=yelan**")
    expect(page.get_by_role("heading", level=1)).to_be_visible()
    titles = page.locator("main article").get_by_role("heading")
    expect(titles.first).to_have_accessible_name(re.compile("yelan", re.IGNORECASE))


def test_checklist_2_filter_dialog_and_combobox(page: Page, app_url: str) -> None:
    open_en(page, app_url)
    trigger = page.get_by_role("button", name=re.compile("^Filters"))
    trigger.click()
    dialog = page.get_by_role("dialog", name="Filters")
    expect(dialog).to_be_visible()
    focused_inside = page.evaluate(
        "() => document.querySelector('dialog#filters').contains(document.activeElement)"
    )
    assert focused_inside

    group = dialog.locator("details").filter(has=page.locator("[role=combobox]")).first
    group.locator("summary").click()
    combo = group.get_by_role("combobox").first
    expect(combo).to_have_accessible_name(re.compile(r"\w"))
    combo.fill("Author")
    expect(combo).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#live-region")).to_have_text(
        re.compile(r"\d+ suggestions?, use the up and down arrows")
    )
    page.keyboard.press("ArrowDown")
    active = combo.get_attribute("aria-activedescendant")
    assert active
    expect(page.locator(f"#{active}")).to_have_attribute("aria-selected", "true")
    expect(page.locator(f"#{active}")).to_have_attribute("role", "option")
    page.keyboard.press("Enter")
    expect(page.locator("#live-region")).to_have_text(re.compile("^Added "))
    page.keyboard.press("Backspace")  # empty field: removes the last chip
    expect(page.locator("#live-region")).to_have_text(re.compile("^Removed "))

    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(trigger).to_be_focused()


def test_checklist_3_active_filter_chips(page: Page, app_url: str) -> None:
    open_en(page, app_url, "/?q=yelan&tag_not=32")
    chip = page.locator(".active-filters a").filter(has_text="Tag Beta")
    expect(chip).to_have_accessible_name(re.compile(r"Tag Beta.*Remove this filter"))


def test_checklist_4_sorting(page: Page, app_url: str) -> None:
    open_en(page, app_url, "/?sort=hot_desc")
    current = page.locator('[aria-current="page"]').filter(has=page.locator("xpath=self::a"))
    expect(page.locator('a[aria-current="page"][href*="sort=hot_desc"]').first).to_be_attached()
    assert current.count() >= 1
    expect(page.get_by_role("combobox", name="More sort orders")).to_be_attached()


def test_checklist_5_detail_page(page: Page, app_url: str) -> None:
    open_en(page, app_url, "/movies/200")
    expect(page.get_by_role("navigation", name=re.compile("breadcrumb", re.IGNORECASE))).to_be_attached()
    expect(page.get_by_role("heading", level=1)).to_have_text("sunrise yelan mix")
    # Decorative duplicates (aria-hidden, out of the tab order) are not exposed to screen readers.
    external = page.locator('main a[target="_blank"]:not([aria-hidden="true"])')
    assert external.count() >= 1
    for index in range(external.count()):
        expect(external.nth(index)).to_have_accessible_name(re.compile("new (window|tab)", re.IGNORECASE))


def test_checklist_6_theme_and_language(page: Page, app_url: str) -> None:
    open_en(page, app_url)
    theme = page.locator("[data-theme-toggle]").first
    expect(theme).to_have_accessible_name("Theme: system (click for dark)")
    theme.click()
    expect(theme).to_have_accessible_name("Theme: dark (click for light)")
    for code in ("zh-Hans", "ja", "en"):
        link = page.locator(f'a[hreflang="{code}"][lang="{code}"]')
        expect(link.first).to_be_attached()
