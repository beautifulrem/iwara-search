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
