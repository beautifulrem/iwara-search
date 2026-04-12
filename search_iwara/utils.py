from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse


BASE_URL = "https://oreno3d.com"
MOVIE_ID_RE = re.compile(r"/movies/(\d+)")
ENTITY_ID_RE = re.compile(r"/(?:authors|tags|origins|characters)/(\d+)")
PAGE_RE = re.compile(r"[?&]page=(\d+)")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", normalized).strip()


def absolute_url(value: str | None) -> str | None:
    if not value:
        return None
    return urljoin(BASE_URL, value)


def parse_compact_number(value: str | None) -> int | None:
    if not value:
        return None
    text = clean_text(value).lower().replace(",", "")
    if not text or text == "なし":
        return None
    multiplier = 1
    if text.endswith("k"):
        multiplier = 1_000
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


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
    return [token for token in re.split(r"[\s,，]+", clean_text(value)) if token]


def fts_query_from_text(value: str, mode: str) -> str | None:
    tokens = split_query_tokens(value)
    if not tokens:
        return None
    joiner = " OR " if mode == "any" else " AND "
    return joiner.join(f'"{token.replace("\"", "\"\"")}"' for token in tokens)


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def parse_csv_ids(value: str | None) -> list[int]:
    if not value:
        return []
    seen: set[int] = set()
    result: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            item = int(part)
        except ValueError:
            continue
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def chunked(items: Iterable[Any], size: int) -> list[list[Any]]:
    bucket: list[Any] = []
    chunks: list[list[Any]] = []
    for item in items:
        bucket.append(item)
        if len(bucket) == size:
            chunks.append(bucket)
            bucket = []
    if bucket:
        chunks.append(bucket)
    return chunks


def page_count(total: int, page_size: int) -> int:
    if total <= 0:
        return 1
    return math.ceil(total / page_size)


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


def update_query_params(current: dict[str, str], **updates: Any) -> str:
    params = dict(current)
    for key, value in updates.items():
        if value in ("", None, [], ()):
            params.pop(key, None)
        else:
            params[key] = str(value)
    return urlencode(params)


def format_number(value: int | None) -> str:
    if value is None:
        return "0"
    return f"{value:,}"


def resolve_page_from_url(url: str) -> int | None:
    query = dict(parse_qsl(urlparse(url).query))
    raw = query.get("page")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
