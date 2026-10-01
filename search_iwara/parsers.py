"""HTML → domain-model parsing for oreno3d.com pages.

Every URL that leaves this module has passed :func:`search_iwara.utils.safe_url`, so the
storage and rendering layers can treat URLs as trusted ``https`` links on known hosts.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from .models import EntityRef, ListingPage, MovieDetail, MovieListItem
from .utils import (
    absolute_url,
    clean_multiline,
    clean_text,
    extract_entity_id,
    extract_movie_id,
    parse_compact_number,
    safe_url,
)

SOURCE_HOSTS: tuple[str, ...] = ("oreno3d.com",)
VIDEO_HOSTS: tuple[str, ...] = ("iwara.tv",)
ICON_PREFIXES = {"face", "local_library", "accessibility_new", "local_offer"}
PLACEHOLDER_PAGE_TITLES = {"|俺の3Dエロ動画", "｜俺の3Dエロ動画"}
PAGE_PARAM_RE = re.compile(r"[?&]page=(\d+)")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class ParserDriftError(ValueError):
    """The page no longer has the structure the parser relies on (site redesign)."""


class DetailUnavailableError(ValueError):
    """The detail page is a placeholder for a removed/private movie."""


def _text(node: Node | None) -> str:
    return "" if node is None else clean_text(node.text())


def _comment(node: Node | None) -> str | None:
    return None if node is None else (clean_multiline(node.text()) or None)


def _source_url(value: str | None, base_url: str) -> str | None:
    return safe_url(absolute_url(value, base_url), SOURCE_HOSTS)


def _entity_name_from_link(node: Node) -> str:
    for selector in (
        ".tag-text",
        ".aside-list-name",
        ".box-text-in",
        "div.video-center",
        "span.video-center",
    ):
        values = [_text(child) for child in node.css(selector)]
        values = [value for value in values if value and value not in ICON_PREFIXES]
        if values:
            return values[-1]

    name = _text(node)
    while True:
        head, _, rest = name.partition(" ")
        if rest and head in ICON_PREFIXES:
            name = clean_text(rest)
            continue
        return name


def _entity_from_link(node: Node | None, base_url: str) -> EntityRef | None:
    if node is None:
        return None
    href = _source_url(node.attributes.get("href"), base_url)
    if not href:
        return None
    name = _entity_name_from_link(node)
    if not name:
        return None
    return EntityRef(source_id=extract_entity_id(href), name=name, url=href)


def _entities_from_links(nodes: list[Node], base_url: str) -> list[EntityRef]:
    seen: set[int] = set()
    results: list[EntityRef] = []
    for node in nodes:
        entity = _entity_from_link(node, base_url)
        if entity is not None and entity.source_id not in seen:
            seen.add(entity.source_id)
            results.append(entity)
    return results


def _is_unavailable_detail_page(
    *,
    title: str,
    page_title: str,
    date_texts: list[str],
    view_count: int | None,
    favorite_count: int | None,
) -> bool:
    return (
        not title
        and page_title in PLACEHOLDER_PAGE_TITLES
        and len(date_texts) >= 2
        and date_texts[0] == "-0001-11-30"
        and date_texts[1] == "00:00"
        and view_count == 0
        and favorite_count == 0
    )


def parse_listing_page(html: str, *, page: int, base_url: str) -> ListingPage:
    tree = HTMLParser(html)
    grid = tree.css_first("div.g-main-grid")
    if grid is None:
        raise ParserDriftError(f"listing page {page}: movie grid (div.g-main-grid) not found")

    items: list[MovieListItem] = []
    for article in grid.css("article"):
        link = article.css_first("a.box")
        if link is None:
            continue
        href = _source_url(link.attributes.get("href"), base_url)
        if not href or "/movies/" not in href:
            continue
        stats = [clean_text(node.text()) for node in article.css(".figure-text-in")]
        thumbnail_node = article.css_first("img.main-thumbnail")
        items.append(
            MovieListItem(
                source_site_id=extract_movie_id(href),
                oreno3d_url=href,
                title=_text(article.css_first("h2.box-h2")),
                author_name=_text(article.css_first(".box-text1 .box-text-in")) or None,
                thumbnail_url=_source_url(
                    thumbnail_node.attributes.get("src") if thumbnail_node else None, base_url
                ),
                view_count=parse_compact_number(stats[0]) if stats else None,
                favorite_count=parse_compact_number(stats[1]) if len(stats) >= 2 else None,
            )
        )

    last_page = page
    for link in tree.css("ul.pagination a.page-link"):
        match = PAGE_PARAM_RE.search(link.attributes.get("href") or "")
        if match:
            last_page = max(last_page, int(match.group(1)))

    return ListingPage(page=page, last_page=last_page, items=items)


def parse_movie_detail(html: str, *, source_site_id: int, oreno3d_url: str, base_url: str) -> MovieDetail:
    tree = HTMLParser(html)
    title = _text(tree.css_first("h1.video-h1"))
    page_title = _text(tree.css_first("title"))

    meta_image = tree.css_first('meta[property="og:image"]')
    thumbnail_url = _source_url(meta_image.attributes.get("content") if meta_image else None, base_url)

    view_count: int | None = None
    favorite_count: int | None = None
    for list_node in tree.css("ul.video-views li.f-label-in"):
        icon = list_node.css_first("i.material-icons")
        values = [_text(node) for node in list_node.css(".video-text")]
        if icon is None or not values:
            continue
        icon_name = clean_text(icon.text())
        if icon_name == "remove_red_eye":
            view_count = parse_compact_number(values[0])
        elif icon_name == "favorite":
            favorite_count = parse_compact_number(values[0])

    date_texts = [_text(node) for node in tree.css("ul.video-views .video-text")]
    published_at = None
    if len(date_texts) >= 2 and DATE_RE.match(date_texts[0]):
        published_at = f"{date_texts[0]} {date_texts[1]}".strip()

    if _is_unavailable_detail_page(
        title=title,
        page_title=page_title,
        date_texts=date_texts,
        view_count=view_count,
        favorite_count=favorite_count,
    ):
        raise DetailUnavailableError(f"Placeholder detail page for movie {source_site_id}")
    if not title:
        raise ParserDriftError(f"movie {source_site_id}: title (h1.video-h1) not found")

    section = "section.video-section-tag"
    author = _entity_from_link(tree.css_first(f'{section} a[href*="/authors/"]'), base_url)
    origins = _entities_from_links(tree.css(f'{section} a[href*="/origins/"]'), base_url)
    characters = _entities_from_links(tree.css(f'{section} a[href*="/characters/"]'), base_url)
    tags = _entities_from_links(tree.css(f'{section} a[href*="/tags/"]'), base_url)

    external_video_url = None
    for link in tree.css("a.video-watch-btn2"):
        candidate = safe_url(absolute_url(link.attributes.get("href"), base_url), VIDEO_HOSTS)
        if candidate:
            external_video_url = candidate
            break

    return MovieDetail(
        source_site_id=source_site_id,
        oreno3d_url=_source_url(oreno3d_url, base_url) or f"{base_url}/movies/{source_site_id}",
        title=title,
        external_video_url=external_video_url,
        author=author,
        tags=tags,
        origins=origins,
        characters=characters,
        thumbnail_url=thumbnail_url,
        published_at=published_at,
        view_count=view_count,
        favorite_count=favorite_count,
        author_comment=_comment(tree.css_first("blockquote.video-information-comment")),
    )
