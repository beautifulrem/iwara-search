from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from search_iwara.config import PACKAGE_ROOT, get_settings
from search_iwara.i18n import SUPPORTED_LANGS, catalog, negotiate, resolve_lang, translate
from search_iwara.logging_setup import JsonFormatter, configure_logging, uvicorn_log_config
from search_iwara.models import SORT_MODES, SearchFilters
from search_iwara.utils import (
    MAX_SAFE_INTEGER,
    pagination_window,
    parse_bounded_int,
    parse_compact_number,
    parse_csv_ids,
    safe_url,
    split_query_tokens,
    update_query_params,
)
from search_iwara.web.formatting import format_compact, format_timestamp, iso_datetime, relative_time
from search_iwara.web.query import SearchParams

# --- utils ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.iwara.tv/video/1", "https://www.iwara.tv/video/1"),
        ("https://iwara.tv/video/1", "https://iwara.tv/video/1"),
        ("HTTPS://WWW.IWARA.TV/video/1", "https://WWW.IWARA.TV/video/1"),
        ("http://www.iwara.tv/video/1", None),
        ("javascript:alert(1)//iwara.tv", None),
        ("https://iwara.tv.evil.com/x", None),
        ("https://eviliwara.tv/x", None),
        ("https://a:b@iwara.tv/x", None),
        ("//iwara.tv/x", None),
        ("", None),
        (None, None),
        ("https://[::1", None),
    ],
)
def test_safe_url(url: str | None, expected: str | None) -> None:
    assert safe_url(url, ("iwara.tv",)) == expected


def test_parse_csv_ids_dedupes_filters_and_caps() -> None:
    assert parse_csv_ids("3, 1,x,3,-2,1.5,,2", limit=10) == [3, 1, 2]
    assert parse_csv_ids(",".join(str(i) for i in range(100)), limit=20) == list(range(20))
    assert parse_csv_ids(str(2**64), limit=5) == []
    assert parse_csv_ids(None, limit=5) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("42", 42),
        (" 1,000 ", 1000),
        ("-5", None),
        ("abc", None),
        ("", None),
        (None, None),
        ("99999999999999999999999", MAX_SAFE_INTEGER),
    ],
)
def test_parse_bounded_int(raw: str | None, expected: int | None) -> None:
    assert parse_bounded_int(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1.4k", 1400), ("2M", 2_000_000), ("1,234", 1234), ("なし", None), ("x", None), (None, None)],
)
def test_parse_compact_number(raw: str | None, expected: int | None) -> None:
    assert parse_compact_number(raw) == expected


def test_query_helpers() -> None:
    assert split_query_tokens("  a，b、c  d ") == ["a", "b", "c", "d"]
    assert pagination_window(1, 5) == [1, 2, 3, 4, 5]
    assert pagination_window(10, 20) == [1, None, 8, 9, 10, 11, 12, None, 20]
    assert update_query_params({"a": "1", "b": "2"}, b=None, c=3) == "a=1&c=3"


def test_filters_round_trip_and_count() -> None:
    filters = SearchFilters(q="x", tag_any=[1, 2], min_views=10, published_from="2026-01-01", sort="hot_desc")
    assert filters.to_query_dict() == {
        "q": "x",
        "tag_any": "1,2",
        "published_from": "2026-01-01",
        "min_views": "10",
        "sort": "hot_desc",
    }
    assert filters.active_filter_count() == 3


# --- web query model --------------------------------------------------------------------------


def test_search_params_are_lenient_inside_limits() -> None:
    params = SearchParams(
        sort="hot", title_mode="weird", published_from="2026-13-40", min_views="abc", tag_any="1,2,x"
    )
    filters = params.to_filters()
    assert filters.sort == "hot_desc"
    assert filters.title_mode == "all"
    assert filters.published_from == ""
    assert filters.min_views is None
    assert filters.tag_any == [1, 2]
    assert SearchParams(sort="nonsense").sort == "published_desc"


def test_search_params_enforce_structural_limits() -> None:
    with pytest.raises(ValidationError):
        SearchParams(q="x" * 201)
    with pytest.raises(ValidationError):
        SearchParams(page=0)
    with pytest.raises(ValidationError):
        SearchParams(tag_any="1," * 200)


# --- formatting -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "lang", "expected"),
    [
        (999, "en", "999"),
        (1500, "en", "1.5K"),
        (2_000_000, "en", "2M"),
        (12_345, "zh-Hans", "1.2万"),
        (9_999, "ja", "9,999"),
        (300_000_000, "zh-Hans", "3亿"),
        (300_000_000, "ja", "3億"),
        (None, "en", "0"),
    ],
)
def test_format_compact(value: int | None, lang: str, expected: str) -> None:
    assert format_compact(value, lang) == expected


def test_relative_time_and_timestamps() -> None:
    now = datetime(2026, 4, 11, 12, 0, tzinfo=UTC)  # 21:00 JST
    assert relative_time("2026-04-11 20:59", "en", now=now) == translate("en", "time.minutes_ago", count=1)
    assert relative_time("2026-04-11 20:59:30", "en", now=now) == "2026-04-11 20:59:30"  # unparseable
    assert relative_time("2026-04-11 21:00", "en", now=now) == translate("en", "time.just_now")
    assert relative_time("2026-04-11 18:00", "ja", now=now) == translate("ja", "time.hours_ago", count=3)
    assert relative_time("2026-04-01", "zh-Hans", now=now) == translate("zh-Hans", "time.days_ago", count=10)
    assert relative_time("2025-01-01 00:00", "en", now=now) == "2025-01-01"
    assert relative_time("2027-01-01 00:00", "en", now=now) == "2027-01-01"
    assert relative_time(None, "en") == ""
    assert iso_datetime("2026-04-11 05:12") == "2026-04-11T05:12:00+09:00"
    assert iso_datetime(None) == ""
    assert format_timestamp("2026-04-11T05:12:00+00:00") == "2026-04-11 05:12 UTC"
    assert format_timestamp("garbage") == "garbage"
    assert format_timestamp(None) == ""


# --- i18n -------------------------------------------------------------------------------------


def has_key(lang: str, key: str) -> bool:
    """A key exists plainly or as CLDR plural variants (``key#one`` / ``key#other``)."""

    return key in catalog(lang) or f"{key}#other" in catalog(lang)


def test_locale_catalogs_share_keys() -> None:
    reference = set(catalog("zh-Hans"))
    for lang in SUPPORTED_LANGS:
        assert set(catalog(lang)) == reference, lang
        assert all(value.strip() for value in catalog(lang).values()), lang


def test_every_literal_template_key_exists() -> None:
    pattern = re.compile(r"""\btr\(\s*['"]([a-z0-9_.]+)['"]""")
    keys: set[str] = set()
    for template in (PACKAGE_ROOT / "templates").rglob("*.html"):
        keys.update(pattern.findall(template.read_text(encoding="utf-8")))
    assert keys, "templates should use the translator"
    literal = {key for key in keys if not key.endswith(".")}  # "entity." ~ kind etc. are prefixes
    assert sorted(key for key in literal if not has_key("zh-Hans", key)) == []
    for prefix in sorted(keys - literal):
        assert any(key.startswith(prefix) for key in catalog("zh-Hans")), prefix
    assert all(f"sort.option.{mode}" in catalog("zh-Hans") for mode in SORT_MODES)


def test_python_referenced_keys_exist() -> None:
    required = ["brand", "meta.tagline", "meta.description", "meta.search_title"]
    required += [
        f"filter.{name}.title"
        for name in (
            "author_any",
            "author_not",
            "origin_any",
            "origin_not",
            "character_any",
            "character_not",
            "tag_all",
            "tag_any",
            "tag_not",
        )
    ]
    required += [f"filter.range.{name}" for name in ("published", "views", "favorites")]
    required += [f"entity.{kind}" for kind in ("characters", "authors", "tags", "origins", "categories")]
    required += ["time.just_now", "time.minutes_ago", "time.hours_ago", "time.days_ago"]
    for lang in SUPPORTED_LANGS:
        assert [key for key in required if not has_key(lang, key)] == [], lang


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("ja-JP,ja;q=0.9,en;q=0.8", "ja"),
        ("en-US,en;q=0.9", "en"),
        ("fr, zh-CN;q=0.5", "zh-Hans"),
        ("fr", None),
        ("", None),
        ("en;q=0, ja;q=0.1", "ja"),
        ("en;q=abc", None),
    ],
)
def test_accept_language_negotiation(header: str, expected: str | None) -> None:
    assert negotiate(header) == expected


def test_resolve_lang_precedence() -> None:
    assert resolve_lang("en", "ja", "zh") == "en"
    assert resolve_lang("xx", "ja", "en") == "ja"
    assert resolve_lang(None, None, "en-GB") == "en"
    assert resolve_lang(None, None, None) == "zh-Hans"
    assert translate("en", "does.not.exist") == "does.not.exist"


# --- config & logging -------------------------------------------------------------------------


def test_settings_validation_and_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SEARCH_IWARA_DB", str(tmp_path / "env.sqlite3"))
    monkeypatch.setenv("SEARCH_IWARA_PROXY", "")
    monkeypatch.setenv("SEARCH_IWARA_REQUEST_RATE", "1.5")
    settings = get_settings()
    assert settings.db_path == tmp_path / "env.sqlite3"
    assert settings.proxy is None
    assert settings.request_rate == 1.5
    assert settings.resolved_backup_dir == tmp_path / "backups"
    assert settings.max_page == settings.max_result_window // settings.page_size
    assert get_settings(db_path=tmp_path / "arg.sqlite3").db_path == tmp_path / "arg.sqlite3"
    assert get_settings(backup_dir="  ").backup_dir is None
    assert get_settings(base_url="https://example.org/").base_url == "https://example.org"
    assert get_settings(proxy="  ").proxy is None
    with pytest.raises(ValidationError):
        get_settings(request_concurrency=0)
    with pytest.raises(ValidationError):
        get_settings(log_format="xml")


def test_json_logging(capsys: pytest.CaptureFixture[str]) -> None:
    assert configure_logging("json", "INFO") == "json"
    logging.getLogger("search_iwara.test").info("hello", extra={"page": 3})
    try:
        raise ValueError("bad")
    except ValueError:
        logging.getLogger("search_iwara.test").exception("failed")
    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert lines[0]["msg"] == "hello"
    assert lines[0]["page"] == 3
    assert "ValueError" in lines[1]["exc"]
    assert configure_logging("text", "WARNING") == "text"
    assert configure_logging("auto", "INFO") in ("text", "json")
    assert uvicorn_log_config("json", "INFO")["formatters"]["default"]["()"].endswith("JsonFormatter")
    assert "format" in uvicorn_log_config("text", "INFO")["formatters"]["default"]
    assert isinstance(JsonFormatter(), logging.Formatter)


# --- round-3 regressions ----------------------------------------------------------------------


def test_unicode_digits_are_not_numbers() -> None:
    assert parse_csv_ids("²,3,٣,１", limit=10) == [3]
    assert parse_bounded_int("²") is None
    assert parse_bounded_int("１２") is None


def test_plural_forms(monkeypatch: pytest.MonkeyPatch) -> None:
    import search_iwara.i18n as i18n

    fake = {
        "en": {"n#one": "{count} item", "n#other": "{count} items", "plain": "p"},
        "ja": {"n#other": "{count} 件"},
        "zh-Hans": {"n": "{count} 个"},
    }
    monkeypatch.setattr(i18n, "catalog", lambda lang: fake.get(lang, {}))
    assert i18n.translate("en", "n", count=1) == "1 item"
    assert i18n.translate("en", "n", count=2) == "2 items"
    assert i18n.translate("ja", "n", count=1) == "1 件"
    assert i18n.translate("zh-Hans", "n", count=1) == "1 个"
    assert i18n.translate("en", "plain", count=True) == "p"
    assert i18n.plural_category("ja", 1) == "other"


def test_highlight_marks_terms_safely() -> None:
    from search_iwara.web.formatting import highlight

    assert str(highlight("Yelan <b>dance</b>", ["yelan", "DANCE"])) == (
        "<mark>Yelan</mark> &lt;b&gt;<mark>dance</mark>&lt;/b&gt;"
    )
    assert str(highlight("abcabc", ["abc", "a"])) == "<mark>abc</mark><mark>abc</mark>"
    assert str(highlight("x<y", [])) == "x&lt;y"
    assert str(highlight(None, ["a"])) == ""


def test_cjk_grams() -> None:
    from search_iwara.storage.search_index import cjk_grams, is_cjk

    assert cjk_grams("初音ミク dance 初音") == "初 初音 音 音ミ ミ ミク ク"
    assert cjk_grams("latin only") == ""
    assert is_cjk("我慢")
    assert not is_cjk("mm")


def test_default_db_path_outside_a_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import search_iwara.config as config

    assert config.default_db_path() == config.PROJECT_ROOT / "data" / "oreno3d.sqlite3"
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    installed = config.default_db_path()
    assert installed.name == "oreno3d.sqlite3"
    assert "search-iwara" in str(installed)
    assert tmp_path not in installed.parents


def test_json_logs_drop_ansi_color_message(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("json", "INFO")
    logging.getLogger("uvicorn.error").info("started", extra={"color_message": "\x1b[32mstarted\x1b[0m"})
    line = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert "color_message" not in line
    assert line["msg"] == "started"


def test_metrics_token_validation() -> None:
    assert get_settings(metrics_token="a" * 16).metrics_token == "a" * 16
    with pytest.raises(ValidationError):
        get_settings(metrics_token="short")
    with pytest.raises(ValidationError):
        get_settings(metrics_token="x" * 20 + "!")


@pytest.mark.parametrize("raw", ["inf", "nan", "1e999", "١٢", "9" * 30, "-5", "1.2.3"])
def test_compact_number_rejects_non_decimal_input(raw: str) -> None:
    assert parse_compact_number(raw) is None


# --- CSS token fallback stays in sync ---------------------------------------------------------


def _declarations(block: str) -> dict[str, str]:
    return {name: value.strip() for name, value in re.findall(r"(--[\w-]+):\s*([^;]+);", block)}


def _rule_body(css: str, selector: str, start: int) -> str:
    open_brace = css.index("{", css.index(selector, start))
    return css[open_brace + 1 : css.index("}", open_brace)]


def test_light_dark_fallback_matches_tokens() -> None:
    """Engines without light-dark() use a hand-maintained fallback; it must mirror the tokens."""

    css = (PACKAGE_ROOT / "static" / "style.css").read_text(encoding="utf-8")
    pairs = {
        name: (light.strip(), dark.strip())
        for name, light, dark in re.findall(
            r"(--[\w-]+):\s*light-dark\(\s*((?:oklch|rgb|hsl)\([^)]*\)|#\w+)\s*,\s*((?:oklch|rgb|hsl)\([^)]*\)|#\w+)\s*\)",
            css,
        )
    }
    assert len(pairs) >= 20
    fallback = css.index("@supports not (color: light-dark(")
    light = _declarations(_rule_body(css, ":root {", fallback))
    dark_media = _declarations(_rule_body(css, ':root:not([data-theme="light"])', fallback))
    dark_forced = _declarations(_rule_body(css, ':root[data-theme="dark"]', fallback))

    assert set(light) == set(pairs)
    assert set(dark_media) == set(pairs)
    assert set(dark_forced) == set(pairs)
    for name, (light_value, dark_value) in pairs.items():
        assert light[name] == light_value, name
        assert dark_media[name] == dark_value, name
        assert dark_forced[name] == dark_value, name


def test_content_language_marks_only_reliable_cases() -> None:
    from search_iwara.web.formatting import content_language, lang_attribute

    assert content_language("キヴォトスの闇") == "ja"  # kana
    assert content_language("한국어 댄스") == "ko"
    assert content_language("原神 舞蹈") is None  # Han only: Chinese or Japanese — leave unmarked
    assert content_language("dance") is None
    assert content_language(None) is None
    assert str(lang_attribute("キヴォトス", "en")) == ' lang="ja"'
    assert str(lang_attribute("キヴォトス", "ja")) == ""  # already the page language
    assert str(lang_attribute("原神", "en")) == ""
