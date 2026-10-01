from pathlib import Path

import pytest

from search_iwara.parsers import (
    DetailUnavailableError,
    ParserDriftError,
    parse_listing_page,
    parse_movie_detail,
)

BASE = "https://oreno3d.com"
FIXTURES = Path(__file__).parent / "fixtures"


LISTING_HTML = """
<html>
  <body>
    <div class="g-main-grid">
      <article>
        <a href="https://oreno3d.com/movies/101" class="box pop_separate">
          <figure class="box-figure">
            <div class="figure-text-in">1.4k</div>
            <div class="figure-text-in">12</div>
            <img class="main-thumbnail" src="/storage/thumbnails_small/thumb-101">
          </figure>
          <h2 class="box-h2">Alpha Signal</h2>
          <div class="box-text1"><div class="box-text-in">Creator A</div></div>
        </a>
      </article>
      <article>
        <a href="https://oreno3d.com/movies/102" class="box pop_separate">
          <figure class="box-figure">
            <div class="figure-text-in">250</div>
            <div class="figure-text-in">3.5k</div>
            <img class="main-thumbnail" src="/storage/thumbnails_small/thumb-102">
          </figure>
          <h2 class="box-h2">Beta Night</h2>
          <div class="box-text1"><div class="box-text-in">Creator B</div></div>
        </a>
      </article>
    </div>
    <ul class="pagination">
      <li><a class="page-link" href="https://oreno3d.com?sort=latest&page=1">1</a></li>
      <li><a class="page-link" href="https://oreno3d.com?sort=latest&page=4">4</a></li>
    </ul>
  </body>
</html>
"""


DETAIL_HTML = """
<html>
  <head>
    <meta property="og:image" content="/storage/thumb-large-101">
  </head>
  <body>
    <h1 class="video-h1">Alpha Signal</h1>
    <ul class="video-views">
      <li class="f-label-in">
        <i class="material-icons">calendar_month</i>
        <div class="video-text">2026-04-11</div>
        <div class="video-text">05:12</div>
      </li>
    </ul>
    <ul class="video-views">
      <li class="f-label-in">
        <i class="material-icons">remove_red_eye</i>
        <div class="video-text">1.5k</div>
      </li>
      <li class="f-label-in">
        <i class="material-icons">favorite</i>
        <div class="video-text">200</div>
      </li>
    </ul>
    <section class="video-section-tag">
      <a href="https://oreno3d.com/authors/10" class="video-information">
        <i class="material-icons">face</i>
        <div class="video-center">Creator A</div>
      </a>
    </section>
    <section class="video-section-tag">
      <a href="https://oreno3d.com/origins/5" class="video-information">
        <i class="material-icons">local_library</i>
        <div class="video-center">Origin X</div>
      </a>
    </section>
    <section class="video-section-tag">
      <a href="https://oreno3d.com/characters/7" class="video-information">
        <i class="material-icons">accessibility_new</i>
        <div class="video-center">Character Y</div>
      </a>
    </section>
    <section class="video-section-tag">
      <ul class="video-tag">
        <li><a href="https://oreno3d.com/tags/1" class="video-tag-btn"><i class="material-icons">local_offer</i><div class="tag-text">Tag One</div></a></li>
        <li><a href="https://oreno3d.com/tags/2" class="video-tag-btn"><i class="material-icons">local_offer</i><div class="tag-text">Tag Two</div></a></li>
      </ul>
    </section>
    <blockquote class="video-information-comment">Hello world comment</blockquote>
    <a href="https://www.iwara.tv/video/example" class="video-watch-btn2">watch</a>
  </body>
</html>
"""


DETAIL_HTML_NO_TAGS = """
<html>
  <body>
    <h1 class="video-h1">Gamma Quiet</h1>
    <ul class="video-views">
      <li class="f-label-in">
        <i class="material-icons">calendar_month</i>
        <div class="video-text">2026-04-10</div>
        <div class="video-text">09:10</div>
      </li>
    </ul>
    <section class="video-section-tag">
      <a href="https://oreno3d.com/authors/11" class="video-information">Creator Z</a>
    </section>
    <a href="https://www.iwara.tv/video/example-2" class="video-watch-btn2">watch</a>
  </body>
</html>
"""


DETAIL_HTML_PLACEHOLDER = """
<html>
  <head>
    <title>｜俺の3Dエロ動画</title>
  </head>
  <body>
    <h1 class="video-h1"></h1>
    <ul class="video-views">
      <li class="f-label-in">
        <i class="material-icons">calendar_month</i>
        <div class="video-text">-0001-11-30</div>
        <div class="video-text">00:00</div>
      </li>
      <li class="f-label-in">
        <i class="material-icons">remove_red_eye</i>
        <div class="video-text">0</div>
        <div class="video-text">回視聴</div>
      </li>
      <li class="f-label-in">
        <i class="material-icons">favorite</i>
        <div class="video-text">0</div>
        <div class="video-text">いいね</div>
      </li>
    </ul>
    <section class="video-section-tag">
      <a href="https://oreno3d.com/authors/10" class="video-information">
        <div class="video-center">Creator A</div>
      </a>
    </section>
    <a href="https://www.iwara.tv/video/example" class="video-watch-btn2">watch</a>
  </body>
</html>
"""


def detail(html: str, source_id: int = 101):
    return parse_movie_detail(
        html, source_site_id=source_id, oreno3d_url=f"{BASE}/movies/{source_id}", base_url=BASE
    )


def test_parse_listing_page_extracts_movies_and_last_page():
    page = parse_listing_page(LISTING_HTML, page=2, base_url=BASE)

    assert page.last_page == 4
    assert len(page.items) == 2
    assert page.items[0].source_site_id == 101
    assert page.items[0].thumbnail_url == "https://oreno3d.com/storage/thumbnails_small/thumb-101"
    assert page.items[0].view_count == 1400
    assert page.items[1].favorite_count == 3500


def test_parse_movie_detail_with_full_metadata():
    parsed = detail(DETAIL_HTML)

    assert parsed.title == "Alpha Signal"
    assert parsed.thumbnail_url == "https://oreno3d.com/storage/thumb-large-101"
    assert parsed.external_video_url == "https://www.iwara.tv/video/example"
    assert parsed.published_at == "2026-04-11 05:12"
    assert parsed.view_count == 1500
    assert parsed.favorite_count == 200
    assert parsed.author is not None
    assert parsed.author.source_id == 10
    assert [tag.source_id for tag in parsed.tags] == [1, 2]
    assert [origin.name for origin in parsed.origins] == ["Origin X"]
    assert [character.name for character in parsed.characters] == ["Character Y"]
    assert parsed.author_comment == "Hello world comment"


def test_parse_movie_detail_without_tags_or_comment():
    parsed = detail(DETAIL_HTML_NO_TAGS, 102)

    assert parsed.tags == []
    assert parsed.origins == []
    assert parsed.characters == []
    assert parsed.author_comment is None
    assert parsed.external_video_url == "https://www.iwara.tv/video/example-2"


def test_parse_movie_detail_placeholder_page_raises_unavailable():
    with pytest.raises(DetailUnavailableError):
        detail(DETAIL_HTML_PLACEHOLDER, 103)


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(document.cookie)//iwara",
        "data:text/html,<script>alert(1)</script>iwara",
        "http://www.iwara.tv/video/plain-http",
        "https://iwara.tv.evil.example/video/x",
        "https://user:pw@www.iwara.tv/video/x",
    ],
)
def test_untrusted_video_links_are_dropped(href: str):
    html = DETAIL_HTML.replace("https://www.iwara.tv/video/example", href)
    assert detail(html).external_video_url is None


def test_untrusted_thumbnail_and_entity_links_are_dropped():
    html = DETAIL_HTML.replace("/storage/thumb-large-101", "javascript:alert(1)").replace(
        "https://oreno3d.com/tags/1", "https://evil.example/tags/1"
    )
    parsed = detail(html)
    assert parsed.thumbnail_url is None
    assert [tag.source_id for tag in parsed.tags] == [2]


def test_listing_without_grid_is_parser_drift():
    with pytest.raises(ParserDriftError):
        parse_listing_page("<html><body><div class='new-layout'></div></body></html>", page=1, base_url=BASE)


def test_detail_without_title_is_parser_drift():
    with pytest.raises(ParserDriftError):
        detail("<html><head><title>Something</title></head><body><h2>moved</h2></body></html>")


def test_duplicate_entity_links_are_collapsed():
    html = DETAIL_HTML.replace(
        '<li><a href="https://oreno3d.com/tags/2"',
        '<li><a href="https://oreno3d.com/tags/1" class="video-tag-btn"><div class="tag-text">Tag One</div></a></li>'
        '<li><a href="https://oreno3d.com/tags/2"',
    )
    assert [tag.source_id for tag in detail(html).tags] == [1, 2]


# --- snapshots of real pages: fail loudly when oreno3d.com changes its markup ---------------


def test_real_listing_snapshot_parses():
    html = (FIXTURES / "listing_page.html").read_text(encoding="utf-8")
    page = parse_listing_page(html, page=1, base_url=BASE)

    assert len(page.items) >= 20
    assert page.last_page > 100
    assert all(item.title for item in page.items)
    assert all(item.thumbnail_url and item.thumbnail_url.startswith(BASE) for item in page.items)
    assert all(item.view_count is not None for item in page.items)


def test_real_detail_snapshot_parses():
    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")
    parsed = parse_movie_detail(html, source_site_id=1, oreno3d_url=f"{BASE}/movies/1", base_url=BASE)

    assert parsed.title
    assert parsed.author is not None
    assert parsed.published_at is not None
    assert parsed.external_video_url is not None
    assert parsed.external_video_url.startswith("https://www.iwara.tv/")
    assert parsed.view_count is not None


def test_comment_keeps_line_breaks_and_decodes_literal_escapes():
    html = DETAIL_HTML.replace("Hello world comment", "line one\\nline  two\n   line three")
    assert detail(html).author_comment == "line one\nline two\nline three"


def test_comment_decodes_php_escapes():
    html = DETAIL_HTML.replace("Hello world comment", 'Who would\\\'ve \\"said\\" it\\r\\nC:\\\\path')
    assert detail(html).author_comment == 'Who would\'ve "said" it\nC:\\path'
