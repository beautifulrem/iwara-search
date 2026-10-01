"""Small, dependency-free helpers shared across layers."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from urllib.parse import urlencode, urljoin, urlsplit

MOVIE_ID_RE = re.compile(r"/movies/(\d+)")
ENTITY_ID_RE = re.compile(r"/(?:authors|tags|origins|characters)/(\d+)")
MAX_SAFE_INTEGER = 2**53 - 1
QUERY_TOKEN_SPLIT_RE = re.compile(r"[\s,，、]+")
# str.isdigit() accepts "²" or "٣", which int() then rejects — only ASCII digits are ids/numbers.
ASCII_DIGITS_RE = re.compile(r"[0-9]+")
DECIMAL_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", normalized).strip()


# Backslash escapes left in descriptions by the source site (JSON newlines, PHP addslashes).
SOURCE_ESCAPE_RE = re.compile(r"\\(r\\n|n|['\"\\])")


def decode_source_escapes(value: str) -> str:
    """``\\n`` / ``\\r\\n`` -> newline, ``\\'`` ``\\"`` ``\\\\`` -> the character (single pass)."""

    return SOURCE_ESCAPE_RE.sub(
        lambda match: "\n" if match.group(1) in ("n", "r\\n") else match.group(1), value
    )


def clean_multiline(value: str | None) -> str:
    """Like :func:`clean_text` but keeps line breaks and decodes the source's escapes."""

    if not value:
        return ""
    normalized = decode_source_escapes(unicodedata.normalize("NFKC", value))
    lines = (re.sub(r"[^\S\n]+", " ", line).strip() for line in normalized.replace("\u200b", "").splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def absolute_url(value: str | None, base_url: str) -> str | None:
    if not value:
        return None
    return urljoin(base_url + "/", value.strip())


def safe_url(value: str | None, allowed_hosts: Iterable[str]) -> str | None:
    """Return ``value`` only if it is an ``https`` URL on an allowed host (or a subdomain).

    This is the single choke point that stops scraped ``javascript:``/``data:`` links or
    look-alike hosts from ever being stored or rendered as ``href``/``src`` attributes.
    """

    if not value:
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    host = parts.hostname.lower().rstrip(".")
    for allowed in (item.lower() for item in allowed_hosts):
        if host == allowed or host.endswith("." + allowed):
            return parts.geturl()
    return None


def parse_compact_number(value: str | None) -> int | None:
    if not value:
        return None
    text = clean_text(value).lower().replace(",", "")
    if not text or text == "なし":
        return None
    multiplier = 1
    if text.endswith("k"):
        multiplier, text = 1_000, text[:-1]
    elif text.endswith("m"):
        multiplier, text = 1_000_000, text[:-1]
    # Only plain decimals: float() would also accept "inf", "nan", "1e999" or "١٢".
    if not DECIMAL_RE.fullmatch(text):
        return None
    number = float(text) * multiplier
    return int(number) if number <= MAX_SAFE_INTEGER else None


def extract_movie_id(url: str) -> int:
    match = MOVIE_ID_RE.search(url)
    if not match:
        raise ValueError(f"Could not parse movie id from {url!r}")
    return int(match.group(1))


def extract_entity_id(url: str) -> int:
    match = ENTITY_ID_RE.search(url)
    if not match:
        raise ValueError(f"Could not parse entity id from {url!r}")
    return int(match.group(1))


def split_query_tokens(value: str) -> list[str]:
    return [token for token in QUERY_TOKEN_SPLIT_RE.split(clean_text(value)) if token]


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def parse_csv_ids(value: str | None, *, limit: int) -> list[int]:
    """Parse ``"1,2,x,2"`` into ``[1, 2]``: invalid parts are dropped, order kept, capped."""

    if not value:
        return []
    seen: set[int] = set()
    result: list[int] = []
    for raw in value.split(","):
        part = raw.strip()
        if not ASCII_DIGITS_RE.fullmatch(part):
            continue
        item = int(part)
        if item > MAX_SAFE_INTEGER or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def parse_bounded_int(value: str | None, *, low: int = 0, high: int = MAX_SAFE_INTEGER) -> int | None:
    """Parse a non-negative integer and clamp it into ``[low, high]``; junk becomes ``None``."""

    if value is None:
        return None
    stripped = value.strip().replace(",", "")
    if not ASCII_DIGITS_RE.fullmatch(stripped):
        return None
    return min(max(int(stripped[:20]), low), high)


def page_count(total: int, page_size: int) -> int:
    return 1 if total <= 0 else math.ceil(total / page_size)


def pagination_window(current: int, total: int, radius: int = 2) -> list[int | None]:
    if total <= 7:
        return list(range(1, total + 1))
    pages: list[int | None] = [1]
    start = max(2, current - radius)
    end = min(total - 1, current + radius)
    if start > 2:
        pages.append(None)
    pages.extend(range(start, end + 1))
    if end < total - 1:
        pages.append(None)
    pages.append(total)
    return pages


def update_query_params(current: Mapping[str, str], **updates: object) -> str:
    params = dict(current)
    for key, value in updates.items():
        if value in ("", None, [], ()):
            params.pop(key, None)
        else:
            params[key] = str(value)
    return urlencode(params)


def href_with_query(path: str, query: str) -> str:
    return f"{path}?{query}" if query else path
