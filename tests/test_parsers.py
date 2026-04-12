import pytest

from search_iwara.parsers import DetailUnavailableError, parse_listing_page, parse_movie_detail


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


def test_parse_listing_page_extracts_movies_and_last_page():
    page = parse_listing_page(LISTING_HTML, page=2)

    assert page.last_page == 4
    assert len(page.items) == 2
    assert page.items[0].source_site_id == 101
    assert page.items[0].thumbnail_url == "https://oreno3d.com/storage/thumbnails_small/thumb-101"
    assert page.items[0].view_count == 1400
    assert page.items[1].favorite_count == 3500


def test_parse_movie_detail_with_full_metadata():
    detail = parse_movie_detail(
        DETAIL_HTML,
        source_site_id=101,
        oreno3d_url="https://oreno3d.com/movies/101",
    )

    assert detail.title == "Alpha Signal"
    assert detail.thumbnail_url == "https://oreno3d.com/storage/thumb-large-101"
    assert detail.external_video_url == "https://www.iwara.tv/video/example"
    assert detail.published_at == "2026-04-11 05:12"
    assert detail.view_count == 1500
    assert detail.favorite_count == 200
    assert detail.author is not None
    assert detail.author.source_id == 10
    assert [tag.source_id for tag in detail.tags] == [1, 2]
    assert [origin.name for origin in detail.origins] == ["Origin X"]
    assert [character.name for character in detail.characters] == ["Character Y"]
    assert detail.author_comment == "Hello world comment"


def test_parse_movie_detail_without_tags_or_comment():
    detail = parse_movie_detail(
        DETAIL_HTML_NO_TAGS,
        source_site_id=102,
        oreno3d_url="https://oreno3d.com/movies/102",
    )

    assert detail.tags == []
    assert detail.origins == []
    assert detail.characters == []
    assert detail.author_comment is None
    assert detail.external_video_url == "https://www.iwara.tv/video/example-2"


def test_parse_movie_detail_placeholder_page_raises_unavailable():
    with pytest.raises(DetailUnavailableError):
        parse_movie_detail(
            DETAIL_HTML_PLACEHOLDER,
            source_site_id=103,
            oreno3d_url="https://oreno3d.com/movies/103",
        )
