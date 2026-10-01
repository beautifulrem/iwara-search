"""Locale catalogs (``locales/<code>.toml``), language negotiation and translation."""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Final

LOCALES_DIR: Final = Path(__file__).resolve().parent / "locales"
DEFAULT_LANG: Final = "zh-Hans"


@dataclass(frozen=True, slots=True)
class Language:
    code: str  # our catalog code, also used for ?lang=
    html_lang: str  # BCP 47 tag for <html lang> / hreflang
    label: str  # endonym shown in the language menu
    prefixes: tuple[str, ...]  # Accept-Language primary tags that map here


LANGUAGES: Final[tuple[Language, ...]] = (
    Language("zh-Hans", "zh-Hans", "简体中文", ("zh",)),
    Language("ja", "ja", "日本語", ("ja",)),
    Language("en", "en", "English", ("en",)),
)
SUPPORTED_LANGS: Final = tuple(language.code for language in LANGUAGES)
LANGUAGE_BY_CODE: Final = {language.code: language for language in LANGUAGES}

Translator = Callable[..., str]


@cache
def catalog(lang: str) -> Mapping[str, str]:
    with (LOCALES_DIR / f"{lang}.toml").open("rb") as handle:
        data = tomllib.load(handle)
    return {str(key): str(value) for key, value in data.items()}


def negotiate(accept_language: str | None) -> str | None:
    """Pick the best supported language from an ``Accept-Language`` header."""

    if not accept_language:
        return None
    candidates: list[tuple[float, int, str]] = []
    for index, part in enumerate(accept_language.split(",")):
        tag, _, params = part.strip().partition(";")
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                quality = 0.0
        primary = tag.strip().lower().split("-")[0]
        candidates.extend(
            (quality, -index, language.code)
            for language in LANGUAGES
            if primary in language.prefixes and quality > 0
        )
    return max(candidates)[2] if candidates else None


def resolve_lang(lang_param: str | None, cookie_lang: str | None, accept_language: str | None = None) -> str:
    for candidate in (lang_param, cookie_lang):
        if candidate in LANGUAGE_BY_CODE:
            return candidate
    return negotiate(accept_language) or DEFAULT_LANG


def plural_category(lang: str, count: int) -> str:
    """CLDR cardinal category; Chinese and Japanese have no grammatical plural."""

    if lang == "en":
        return "one" if count == 1 else "other"
    return "other"


def translate(lang: str, key: str, **kwargs: object) -> str:
    """Look up ``key``; with an integer ``count`` prefer ``key#one`` / ``key#other`` forms."""

    candidates = [key]
    count = kwargs.get("count")
    if isinstance(count, int) and not isinstance(count, bool):
        candidates = [f"{key}#{plural_category(lang, count)}", f"{key}#other", key]
    for source in (catalog(lang), catalog(DEFAULT_LANG)):
        for candidate in candidates:
            if candidate in source:
                text = source[candidate]
                return text.format(**kwargs) if kwargs else text
    return key


def build_translator(lang: str) -> Translator:
    def _tr(key: str, **kwargs: object) -> str:
        return translate(lang, key, **kwargs)

    return _tr
