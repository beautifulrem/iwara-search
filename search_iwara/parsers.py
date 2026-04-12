from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from .models import EntityRef, ListingPage, MovieDetail, MovieListItem
from .utils import absolute_url, clean_text, extract_entity_id, extract_movie_id, parse_compact_number

ICON_PREFIXES = {"face", "local_library", "accessibility_new", "local_offer"}
PLACEHOLDER_PAGE_TITLES = {"|俺の3Dエロ動画", "｜俺の3Dエロ動画"}


class DetailUnavailableError(ValueError):
    pass


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return clean_text(node.text())


def _entity_name_from_link(node: Node) -> str:
    prioritized_selectors = (
        ".tag-text",
        ".aside-list-name",
        ".box-text-in",
        "div.video-center",
        "span.video-center",
    )
    for selector in prioritized_selectors:
        values = [_text(child) for child in node.css(selector)]
        values = [value for value in values if value and value not in ICON_PREFIXES]
        if values:
            return values[-1]

    name = _text(node)
    while True:
        parts = name.split(" ", 1)
        if len(parts) == 2 and parts[0] in ICON_PREFIXES:
            name = clean_text(parts[1])
            continue
        break
    return name


def _entity_from_link(node: Node | None) -> EntityRef | None:
    if node is None:
        return None
    href = absolute_url(node.attributes.get("href"))
    if not href:
        return None
    return EntityRef(
        source_id=extract_entity_id(href),
        name=_entity_name_from_link(node),
        url=href,
    )


def _entities_from_links(nodes: list[Node]) -> list[EntityRef]:
    results: list[EntityRef] = []
    for node in nodes:
        entity = _entity_from_link(node)
        if entity is not None:
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


def parse_listing_page(html: str, *, page: int) -> ListingPage:
    tree = HTMLParser(html)
    items: list[MovieListItem] = []
    for article in tree.css("div.g-main-grid > article"):
        link = article.css_first("a.box")
        if link is None:
            continue
        href = absolute_url(link.attributes.get("href"))
        if not href or "/movies/" not in href:
            continue
        stats = [clean_text(node.text()) for node in article.css(".figure-text-in")]
        author_name = _text(article.css_first(".box-text1 .box-text-in")) or None
        item = MovieListItem(
            source_site_id=extract_movie_id(href),
            oreno3d_url=href,
            title=_text(article.css_first("h2.box-h2")),
            author_name=author_name,
            thumbnail_url=absolute_url(
                article.css_first("img.main-thumbnail").attributes.get("src")
                if article.css_first("img.main-thumbnail")
                else None
            ),
            view_count=parse_compact_number(stats[0]) if len(stats) >= 1 else None,
            favorite_count=parse_compact_number(stats[1]) if len(stats) >= 2 else None,
        )
        items.append(item)

    last_page = page
    for link in tree.css("ul.pagination a.page-link"):
        href = absolute_url(link.attributes.get("href"))
        if not href:
            continue
        match = re.search(r"[?&]page=(\d+)", href)
        if match:
            last_page = max(last_page, int(match.group(1)))

    return ListingPage(page=page, last_page=last_page, items=items)


def parse_movie_detail(html: str, *, source_site_id: int, oreno3d_url: str) -> MovieDetail:
    tree = HTMLParser(html)
    title = _text(tree.css_first("h1.video-h1"))
    page_title = _text(tree.css_first("title"))

    meta_image = tree.css_first('meta[property="og:image"]')
    thumbnail_url = absolute_url(meta_image.attributes.get("content") if meta_image else None)

    view_count = None
    favorite_count = None
    for list_node in tree.css("ul.video-views li.f-label-in"):
        icon = list_node.css_first("i.material-icons")
        if icon is None:
            continue
        icon_name = clean_text(icon.text())
        values = [_text(node) for node in list_node.css(".video-text")]
        if icon_name == "remove_red_eye" and values:
            view_count = parse_compact_number(values[0])
        elif icon_name == "favorite" and values:
            favorite_count = parse_compact_number(values[0])

    date_texts = [_text(node) for node in tree.css("ul.video-views .video-text")]
    published_at = None
    if len(date_texts) >= 2 and re.match(r"\d{4}-\d{2}-\d{2}", date_texts[0]):
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
        raise ValueError(f"Could not find detail title for movie {source_site_id}")

    author = _entity_from_link(tree.css_first('section.video-section-tag a[href*="/authors/"]'))
    origins = _entities_from_links(tree.css('section.video-section-tag a[href*="/origins/"]'))
    characters = _entities_from_links(tree.css('section.video-section-tag a[href*="/characters/"]'))
    tags = _entities_from_links(tree.css('section.video-section-tag a[href*="/tags/"]'))

    external_video_url = None
    for link in tree.css("a.video-watch-btn2"):
        href = absolute_url(link.attributes.get("href"))
        if href and "iwara" in href:
            external_video_url = href
            break

    comment = _text(tree.css_first("blockquote.video-information-comment")) or None

    return MovieDetail(
        source_site_id=source_site_id,
        oreno3d_url=oreno3d_url,
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
        author_comment=comment,
    )
