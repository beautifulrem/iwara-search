"""Full-text index maintenance: a trigram document and a short-token document per movie.

* ``movie_search`` (FTS5 ``trigram``) serves substring queries of three or more characters.
* ``movie_search_short`` (FTS5 ``unicode61`` with 1- and 2-character prefix indexes) serves
  the short queries trigrams cannot: every CJK unigram and bigram is stored as its own token
  (so "水着" or "夏" are exact index lookups), and the original words are stored too, so a
  one- or two-letter Latin query ("mm", "3d") becomes an indexed *word-prefix* match
  ("mm" -> "MMD") instead of a table scan.

On SQLite >= 3.43 with trigram support, both tables omit shadow ``%_content`` storage via
``content='', contentless_delete=1`` (and ``detail=none`` on ``movie_search_short``), cutting
FTS disk usage by more than half while retaining ``DELETE``, ``optimize`` and ``integrity-check``.
Only ``status = 'active'`` movies are indexed.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Final

from .connection import contentless_delete_supported, trigram_supported
from .sql import SEARCH_DOCUMENT_SELECT

# Hiragana, Katakana (+ phonetic ext.), CJK Ext-A, CJK Unified, Compatibility, Hangul syllables.
CJK_RUN_RE: Final = re.compile(
    r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]+"
)
STREAM_BATCH_SIZE: Final = 5_000


def is_cjk(text: str) -> bool:
    return CJK_RUN_RE.fullmatch(text) is not None


def cjk_grams(text: str) -> str:
    """Space-separated, de-duplicated unigrams and bigrams of every CJK run in ``text``."""

    grams: dict[str, None] = {}
    for run in CJK_RUN_RE.findall(text):
        for index, char in enumerate(run):
            grams[char] = None
            if index + 1 < len(run):
                grams[run[index : index + 2]] = None
    return " ".join(grams)


def short_token_document(title: str, keywords: str) -> str:
    """Document for ``movie_search_short``: CJK n-grams followed by the non-CJK words."""

    text = f"{title} {keywords}"
    return f"{cjk_grams(text)} {CJK_RUN_RE.sub(' ', text)}".strip()


def movie_search_ddl(tokenizer: str | None = None, *, compact: bool | None = None) -> str:
    tok = tokenizer or ("trigram" if trigram_supported() else "unicode61")
    use_compact = (tok == "trigram" and contentless_delete_supported()) if compact is None else compact
    # Note: SQLite FTS5 §4.3.4 requires detail=full (default) on trigram tables for >3-char queries;
    # non-trigram fallback (< 3.34) needs stored column content for LIKE queries.
    extra = ", content='', contentless_delete=1" if (use_compact and tok == "trigram") else ""
    return f"CREATE VIRTUAL TABLE movie_search USING fts5(title, keywords, tokenize='{tok}'{extra})"


def movie_search_short_ddl(*, compact: bool | None = None) -> str:
    use_compact = contentless_delete_supported() if compact is None else compact
    extra = (
        ", content='', contentless_delete=1, detail=none" if use_compact else ", columnsize=0, detail=none"
    )
    return (
        "CREATE VIRTUAL TABLE movie_search_short "
        f"USING fts5(terms, tokenize='unicode61', prefix='1 2'{extra})"
    )


def index_movie(conn: sqlite3.Connection, movie_id: int) -> None:
    row = conn.execute(
        f"{SEARCH_DOCUMENT_SELECT} WHERE m.id = ? AND m.status = 'active'", (movie_id,)
    ).fetchone()
    conn.execute("DELETE FROM movie_search WHERE rowid = ?", (movie_id,))
    conn.execute("DELETE FROM movie_search_short WHERE rowid = ?", (movie_id,))
    if row is None:
        return
    title, keywords = str(row[1]), str(row[2])
    conn.execute(
        "INSERT INTO movie_search(rowid, title, keywords) VALUES (?, ?, ?)", (movie_id, title, keywords)
    )
    conn.execute(
        "INSERT INTO movie_search_short(rowid, terms) VALUES (?, ?)",
        (movie_id, short_token_document(title, keywords)),
    )


def rebuild_short_index(conn: sqlite3.Connection) -> None:
    """Stream-populate ``movie_search_short`` from active movies in bounded memory chunks."""

    conn.execute("DELETE FROM movie_search_short")
    cursor = conn.execute(f"{SEARCH_DOCUMENT_SELECT} WHERE m.status = 'active'")
    while batch := cursor.fetchmany(STREAM_BATCH_SIZE):
        conn.executemany(
            "INSERT INTO movie_search_short(rowid, terms) VALUES (?, ?)",
            ((int(row[0]), short_token_document(str(row[1]), str(row[2]))) for row in batch),
        )


def rebuild_all_indexes(conn: sqlite3.Connection, *, tokenizer: str | None = None) -> str:
    """Drop, recreate and stream-populate both FTS5 indexes over active movies, then optimize."""

    tok = tokenizer or ("trigram" if trigram_supported() else "unicode61")
    conn.execute("DROP TABLE IF EXISTS movie_search")
    conn.execute("DROP TABLE IF EXISTS movie_search_short")
    conn.execute(movie_search_ddl(tok))
    conn.execute(movie_search_short_ddl())
    cursor = conn.execute(f"{SEARCH_DOCUMENT_SELECT} WHERE m.status = 'active'")
    while batch := cursor.fetchmany(STREAM_BATCH_SIZE):
        docs = [(int(r[0]), str(r[1]), str(r[2])) for r in batch]
        conn.executemany("INSERT INTO movie_search(rowid, title, keywords) VALUES (?, ?, ?)", docs)
        conn.executemany(
            "INSERT INTO movie_search_short(rowid, terms) VALUES (?, ?)",
            ((rowid, short_token_document(title, kw)) for rowid, title, kw in docs),
        )
    optimize_indexes(conn)
    return tok


def optimize_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO movie_search(movie_search) VALUES ('optimize')")
    conn.execute("INSERT INTO movie_search_short(movie_search_short) VALUES ('optimize')")


def verify_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO movie_search(movie_search) VALUES ('integrity-check')")
    conn.execute("INSERT INTO movie_search_short(movie_search_short) VALUES ('integrity-check')")
