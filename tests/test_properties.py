"""Property-based tests: parsers of untrusted input never raise and stay within their contracts."""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st
from markupsafe import escape
from pydantic import ValidationError

from search_iwara.crawler import parse_retry_after
from search_iwara.storage.search_index import cjk_grams
from search_iwara.utils import (
    MAX_SAFE_INTEGER,
    parse_bounded_int,
    parse_compact_number,
    parse_csv_ids,
    safe_url,
    split_query_tokens,
)
from search_iwara.web.formatting import highlight
from search_iwara.web.query import SearchParams

# Text that mixes ASCII, Unicode digits ("²", "٣", "１"), CJK, whitespace and punctuation.
untrusted = st.text(
    alphabet=st.one_of(
        st.characters(codec="utf-8"),
        st.sampled_from(list("0123456789²³٣１,，、 -_%")),
    ),
    max_size=80,
)


@given(untrusted, st.integers(min_value=1, max_value=50))
def test_parse_csv_ids_contract(value: str, limit: int) -> None:
    ids = parse_csv_ids(value, limit=limit)
    assert len(ids) <= limit
    assert len(set(ids)) == len(ids)
    assert all(0 <= item <= MAX_SAFE_INTEGER for item in ids)


@given(untrusted)
def test_parse_bounded_int_contract(value: str) -> None:
    result = parse_bounded_int(value, low=0, high=1000)
    assert result is None or 0 <= result <= 1000


@given(untrusted)
def test_number_and_header_parsers_never_raise(value: str) -> None:
    parse_compact_number(value)
    retry = parse_retry_after(value)
    assert retry is None or retry >= 0


@given(untrusted)
def test_safe_url_only_returns_allowed_https(value: str) -> None:
    for candidate in (value, f"https://{value}", f"https://iwara.tv/{value}"):
        result = safe_url(candidate, ("iwara.tv",))
        assert result is None or result.lower().startswith("https://")


@given(untrusted)
def test_query_tokens_are_clean(value: str) -> None:
    for token in split_query_tokens(value):
        assert token
        assert not re.search(r"[\s,，、]", token)


@given(untrusted, st.lists(untrusted, max_size=4))
def test_highlight_preserves_escaped_text(text: str, terms: list[str]) -> None:
    rendered = str(highlight(text, terms))
    assert rendered.replace("<mark>", "").replace("</mark>", "") == str(escape(text))


@given(untrusted)
def test_cjk_grams_are_short_tokens(value: str) -> None:
    assert all(1 <= len(gram) <= 2 for gram in cjk_grams(value).split())


@settings(max_examples=200)
@given(
    st.dictionaries(
        st.sampled_from(
            [
                "q",
                "title_mode",
                "tag_any",
                "tag_all",
                "author_not",
                "published_from",
                "min_views",
                "sort",
                "page",
            ]
        ),
        untrusted,
    )
)
def test_search_params_validate_or_reject_cleanly(raw: dict[str, str]) -> None:
    try:
        params = SearchParams.model_validate(raw)
    except ValidationError:
        return
    filters = params.to_filters()
    assert len(filters.q) <= 200
    assert all(len(getattr(filters, name)) <= 20 for name in ("tag_any", "tag_all", "author_not"))


# --- Search Oracle Equivalence (Indexed FTS5 + SQL vs Pure-Python Reference Spec) ------------


def _build_oracle_corpus() -> tuple[object, list[dict[str, object]]]:
    import sqlite3

    from search_iwara.models import EntityRef, MovieDetail
    from search_iwara.storage import CrawlStore, migrate

    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    store = CrawlStore(conn)

    raw_docs = [
        (
            1,
            "【MMD】夜兰 水着 ダンス 4K",
            (1, "Kaede"),
            [(1, "MMD"), (2, "4K"), (3, "水着")],
            [(1, "Yelan")],
            [(1, "原神")],
            "2026-05-10 12:00",
            1200,
            80,
            "active",
        ),
        (
            2,
            "キヴォトス 放課後 ライブ 60fps",
            (2, "HoshinoLab"),
            [(1, "MMD"), (4, "60fps")],
            [(2, "ホシノ")],
            [(2, "ブルアカ")],
            "2026-06-15 18:30",
            5400,
            320,
            "active",
        ),
        (
            3,
            "崩坏 流萤 夏日 练习曲 Shader",
            (1, "Kaede"),
            [(2, "4K"), (5, "RayTracing")],
            [(3, "流萤")],
            [(3, "崩坏")],
            "2026-01-20 09:00",
            400,
            15,
            "active",
        ),
        (
            4,
            "유나 Stage Dance Loop",
            (3, "StudioKR"),
            [(3, "水着"), (4, "60fps")],
            [(4, "유나")],
            [(4, "Original")],
            "2025-11-02 21:00",
            8800,
            90,
            "active",
        ),
        (
            5,
            "Missing Deleted Yelan 4K",
            (1, "Kaede"),
            [(1, "MMD"), (2, "4K")],
            [(1, "Yelan")],
            [(1, "原神")],
            "2026-07-01 10:00",
            9999,
            999,
            "missing",
        ),
        (
            6,
            "Suppressed Tombstone 水着",
            (2, "HoshinoLab"),
            [(3, "水着")],
            [(2, "ホシノ")],
            [(2, "ブルアカ")],
            "2026-08-01 10:00",
            7777,
            777,
            "suppressed",
        ),
        # Movie 7 triggers an upstream rename of Author 1 ("Kaede" -> "KaedeVFX") & Tag 5 ("RayTracing" -> "PathTracing")
        (
            7,
            "Encore Night Stage 3D M字開脚 第1話 ドM",
            (1, "KaedeVFX"),
            [(1, "MMD"), (5, "PathTracing")],
            [(1, "Yelan")],
            [(1, "原神")],
            "2026-09-12 14:00",
            2500,
            210,
            "active",
        ),
    ]
    for sid, title, author, tags, chars, origins, pub, views, favs, status in raw_docs:
        store.apply_movie_detail(
            MovieDetail(
                source_site_id=sid,
                oreno3d_url=f"https://oreno3d.com/movies/{sid}",
                title=title,
                external_video_url=f"https://www.iwara.tv/video/{sid}",
                author=EntityRef(*author),
                tags=[EntityRef(*t) for t in tags],
                origins=[EntityRef(*o) for o in origins],
                characters=[EntityRef(*c) for c in chars],
                thumbnail_url=None,
                published_at=pub,
                view_count=views,
                favorite_count=favs,
                author_comment=None,
            )
        )
        if status == "missing":
            store.mark_movie_missing(sid, f"https://oreno3d.com/movies/{sid}")
        elif status == "suppressed":
            store.suppress_movies([sid])
    store.refresh_derived(full=True)

    # Read ground-truth post-rename active documents for the pure-Python reference evaluator
    active_specs: list[dict[str, object]] = []
    for sid, title, (aid, _), tags, chars, origins, pub, views, favs, status in raw_docs:
        if status != "active":
            continue
        aname = "KaedeVFX" if aid == 1 else dict([author for _, _, author, *_ in raw_docs])[aid]
        tnames = ["PathTracing" if tid == 5 else tname for tid, tname in tags]
        full_text = f"{title} {aname} {' '.join(c for _, c in chars)} {' '.join(o for _, o in origins)} {' '.join(tnames)}"
        active_specs.append(
            {
                "id": sid,
                "text": full_text,
                "author": aid,
                "tags": {tid for tid, _ in tags},
                "chars": {cid for cid, _ in chars},
                "origins": {oid for oid, _ in origins},
                "published_at": pub,
                "views": views,
                "favorites": favs,
                "popularity": views + favs * 50,
            }
        )
    return store, active_specs


_ORACLE_STORE, _ORACLE_SPECS = _build_oracle_corpus()


def _token_matches_doc(token: str, doc_text: str) -> bool:
    from search_iwara.storage.search_index import CJK_RUN_RE, is_cjk, mixed_grams

    if len(token) >= 3:
        return token.casefold() in doc_text.casefold()
    if is_cjk(token):
        return token in cjk_grams(doc_text).split()
    mixed = [g.casefold() for g in mixed_grams(doc_text).split()]
    non_cjk_words = re.findall(r"[0-9A-Za-z]+", CJK_RUN_RE.sub(" ", doc_text))
    return any(w.casefold().startswith(token.casefold()) for w in [*non_cjk_words, *mixed])


@settings(max_examples=200)
@given(
    q_parts=st.lists(
        st.sampled_from(
            [
                "MMD",
                "ｍｍｄ",
                "４Ｋ",
                "60",
                "3d",
                "M字",
                "ドM",
                "第1",
                "1話",
                "水着",
                "夏",
                "キヴォトス",
                "放課",
                "KaedeVFX",
                "OldKaede",
                "PathTracing",
                "RayTracing",
                "유나",
                "yelan",
                "nonexistent",
            ]
        ),
        max_size=3,
    ),
    title_mode=st.sampled_from(["all", "any"]),
    tag_all=st.lists(st.sampled_from([1, 2, 3, 4, 5, 99]), max_size=2, unique=True),
    tag_any=st.lists(st.sampled_from([1, 2, 3, 4, 5, 99]), max_size=2, unique=True),
    tag_not=st.lists(st.sampled_from([1, 2, 3, 4, 5, 99]), max_size=2, unique=True),
    author_any=st.lists(st.sampled_from([1, 2, 3, 99]), max_size=2, unique=True),
    author_not=st.lists(st.sampled_from([1, 2, 3, 99]), max_size=1, unique=True),
    char_any=st.lists(st.sampled_from([1, 2, 3, 4]), max_size=2, unique=True),
    published_from=st.sampled_from(["", "2026-01-01", "2026-06-01"]),
    published_to=st.sampled_from(["", "2026-06-30", "2026-12-31"]),
    min_views=st.sampled_from([None, 1000, 5000]),
    sort=st.sampled_from(
        ["published_desc", "published_asc", "views_desc", "favorites_desc", "popularity_desc"]
    ),
    page=st.sampled_from([1, 2, 5]),
)
def test_search_store_matches_python_reference_oracle(
    q_parts: list[str],
    title_mode: str,
    tag_all: list[int],
    tag_any: list[int],
    tag_not: list[int],
    author_any: list[int],
    author_not: list[int],
    char_any: list[int],
    published_from: str,
    published_to: str,
    min_views: int | None,
    sort: str,
    page: int,
) -> None:
    from search_iwara.models import SearchFilters
    from search_iwara.storage import CrawlStore, SearchStore

    assert isinstance(_ORACLE_STORE, CrawlStore)
    search = SearchStore(_ORACLE_STORE.conn)
    q = " ".join(q_parts)
    flt = SearchFilters(
        q=q,
        title_mode=title_mode,  # type: ignore[arg-type]
        tag_all=tag_all,
        tag_any=tag_any,
        tag_not=tag_not,
        author_any=author_any,
        author_not=author_not,
        character_any=char_any,
        published_from=published_from,
        published_to=published_to,
        min_views=min_views,
        sort=sort,  # type: ignore[arg-type]
    )

    tokens = split_query_tokens(q)[:8]
    matched: list[dict[str, object]] = []
    for doc in _ORACLE_SPECS:
        text = str(doc["text"])
        if tokens:
            checks = [_token_matches_doc(tok, text) for tok in tokens]
            if not (any(checks) if title_mode == "any" else all(checks)):
                continue
        tags = doc["tags"]
        assert isinstance(tags, set)
        if tag_all and not set(tag_all).issubset(tags):
            continue
        if tag_any and not (set(tag_any) & tags):
            continue
        if tag_not and (set(tag_not) & tags):
            continue
        if author_any and doc["author"] not in author_any:
            continue
        if author_not and doc["author"] in author_not:
            continue
        chars = doc["chars"]
        assert isinstance(chars, set)
        if char_any and not (set(char_any) & chars):
            continue
        pub = str(doc["published_at"])
        if published_from and pub < published_from:
            continue
        if published_to and pub >= published_to + " 99:99":  # YYYY-MM-DD HH:MM < date(to, '+1 day')
            continue
        if min_views is not None and int(doc["views"]) < min_views:  # type: ignore[arg-type]
            continue
        matched.append(doc)

    sort_keys = {
        "published_desc": lambda d: (str(d["published_at"]), int(d["id"])),  # type: ignore[arg-type]
        "published_asc": lambda d: (str(d["published_at"]), int(d["id"])),  # type: ignore[arg-type]
        "views_desc": lambda d: (int(d["views"]), str(d["published_at"]), int(d["id"])),  # type: ignore[arg-type]
        "favorites_desc": lambda d: (int(d["favorites"]), str(d["published_at"]), int(d["id"])),  # type: ignore[arg-type]
        "popularity_desc": lambda d: (int(d["popularity"]), int(d["id"])),  # type: ignore[arg-type]
    }
    matched.sort(key=sort_keys[sort], reverse=(sort != "published_asc"))
    expected_all = [int(d["id"]) for d in matched]  # type: ignore[arg-type]

    page_size = 3
    res = search.search(flt, page=page, page_size=page_size, max_results=100)
    assert res.total == len(expected_all)
    expected_pages = max(1, -(-len(expected_all) // page_size))
    actual_page = min(max(page, 1), expected_pages)
    expected_slice = expected_all[(actual_page - 1) * page_size : actual_page * page_size]
    assert [item.source_site_id for item in res.items] == expected_slice
