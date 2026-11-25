"""Locale-aware presentation helpers exposed to templates as Jinja filters."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from markupsafe import Markup, escape

from ..i18n import translate

SOURCE_TZ: Final = ZoneInfo("Asia/Tokyo")  # oreno3d.com publishes timestamps in JST


def format_number(value: int | float | None) -> str:
    return f"{int(value or 0):,}"


def format_compact(value: int | float | None, lang: str) -> str:
    number = int(value or 0)
    if lang in ("zh-Hans", "ja"):
        for size, unit in ((100_000_000, "亿" if lang == "zh-Hans" else "億"), (10_000, "万")):
            if number >= size:
                return f"{number / size:.1f}".rstrip("0").rstrip(".") + unit
        return format_number(number)
    for size, unit in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if number >= size:
            return f"{number / size:.1f}".rstrip("0").rstrip(".") + unit
    return str(number)


def parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=SOURCE_TZ)
        except ValueError:
            continue
    return None


def iso_datetime(value: str | None) -> str:
    moment = parse_published(value)
    return "" if moment is None else moment.isoformat()


def relative_time(value: str | None, lang: str, *, now: datetime | None = None) -> str:
    moment = parse_published(value)
    if moment is None:
        return value or ""
    current = now or datetime.now(UTC)
    seconds = (current - moment).total_seconds()
    if seconds < 0:
        return moment.strftime("%Y-%m-%d")
    minutes = int(seconds // 60)
    if minutes < 1:
        return translate(lang, "time.just_now")
    if minutes < 60:
        return translate(lang, "time.minutes_ago", count=minutes)
    hours = minutes // 60
    if hours < 24:
        return translate(lang, "time.hours_ago", count=hours)
    days = hours // 24
    if days < 30:
        return translate(lang, "time.days_ago", count=days)
    return moment.strftime("%Y-%m-%d")


def format_timestamp(value: str | None) -> str:
    """ISO-8601 UTC timestamp (as stored by the crawler) → ``YYYY-MM-DD HH:MM UTC``."""

    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def highlight(text: str | None, terms: Sequence[str]) -> Markup:
    """Escape ``text`` and wrap case-insensitive occurrences of ``terms`` in ``<mark>``."""

    value = text or ""
    needles = sorted({term for term in terms if term}, key=len, reverse=True)
    if not needles:
        return escape(value)
    pattern = re.compile("|".join(re.escape(term) for term in needles), re.IGNORECASE)
    pieces: list[str] = []
    position = 0
    for match in pattern.finditer(value):
        pieces.append(str(escape(value[position : match.start()])))
        pieces.append(f"<mark>{escape(match.group(0))}</mark>")
        position = match.end()
    pieces.append(str(escape(value[position:])))
    return Markup("".join(pieces))  # noqa: S704 - every piece above is escaped


KANA_RE: Final = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
HANGUL_RE: Final = re.compile(r"[\uac00-\ud7af\u1100-\u11ff]")


def content_language(text: str | None) -> str | None:
    """Language of third-party text when it can be told reliably (WCAG 3.1.2), else ``None``.

    Kana means Japanese and Hangul means Korean; text made only of Han characters could be
    Chinese or Japanese, and a wrong ``lang`` is worse than none, so it is left unmarked.
    """

    if not text:
        return None
    if KANA_RE.search(text):
        return "ja"
    if HANGUL_RE.search(text):
        return "ko"
    return None


def lang_attribute(text: str | None, page_lang: str) -> Markup:
    detected = content_language(text)
    if detected is None or page_lang.split("-", maxsplit=1)[0] == detected:
        return Markup("")
    return Markup(' lang="{}"').format(detected)


HTTPS_URL_RE: Final = re.compile(r"https://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")
TRAILING_PUNCT: Final = ".,;:!?)]}"


def _split_url_trailing_punct(raw: str) -> tuple[str, str]:
    url = raw
    trailing: list[str] = []
    while url and url[-1] in TRAILING_PUNCT:
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        trailing.append(url[-1])
        url = url[:-1]
    return url, "".join(reversed(trailing))


def linkify_comment(text: str | None, *, new_window_hint: str = "(opens in a new window)") -> Markup:
    """Escape creator notes and safely linkify external ``https://`` URLs."""

    value = text or ""
    if "https://" not in value:
        return escape(value)
    pieces: list[str] = []
    position = 0
    escaped_hint = escape(new_window_hint)
    for match in HTTPS_URL_RE.finditer(value):
        pieces.append(str(escape(value[position : match.start()])))
        candidate, suffix = _split_url_trailing_punct(match.group(0))
        valid = False
        try:
            parts = urlsplit(candidate)
            valid = (
                parts.scheme == "https"
                and parts.username is None
                and parts.password is None
                and bool(parts.hostname and "." in parts.hostname)
            )
        except ValueError:
            valid = False
        if valid:
            escaped_url = escape(candidate)
            pieces.append(
                f'<a class="comment__link" href="{escaped_url}" target="_blank" '
                f'rel="noopener noreferrer">{escaped_url}'
                f'<span class="sr-only"> {escaped_hint}</span></a>'
            )
            pieces.append(str(escape(suffix)))
        else:
            pieces.append(str(escape(match.group(0))))
        position = match.end()
    pieces.append(str(escape(value[position:])))
    return Markup("".join(pieces))  # noqa: S704 - every piece above is escaped
