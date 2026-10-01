"""Full-text index maintenance: a trigram document and a short-token document per movie.

* ``movie_search`` (FTS5 ``trigram``) serves substring queries of three or more characters.
* ``movie_search_short`` (FTS5 ``unicode61`` with 1- and 2-character prefix indexes) serves
  the short queries trigrams cannot: every CJK unigram and bigram is stored as its own token
  (so "水着" or "夏" are exact index lookups), and the original words are stored too, so a
  one- or two-letter Latin query ("mm", "3d") becomes an indexed *word-prefix* match
  ("mm" -> "MMD") instead of a table scan.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Final

from .sql import SEARCH_DOCUMENT_SELECT

# Hiragana, Katakana (+ phonetic ext.), CJK Ext-A, CJK Unified, Compatibility, Hangul syllables.
CJK_RUN_RE: Final = re.compile(
    r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]+"
)


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


def index_movie(conn: sqlite3.Connection, movie_id: int) -> None:
    row = conn.execute(f"{SEARCH_DOCUMENT_SELECT} WHERE m.id = ?", (movie_id,)).fetchone()
    conn.execute("DELETE FROM movie_search WHERE rowid = ?", (movie_id,))
    conn.execute("DELETE FROM movie_search_short WHERE rowid = ?", (movie_id,))
    if row is None:
        return
    title, keywords = row[1], row[2]
    conn.execute(
        "INSERT INTO movie_search(rowid, title, keywords) VALUES (?, ?, ?)", (movie_id, title, keywords)
    )
    conn.execute(
        "INSERT INTO movie_search_short(rowid, terms) VALUES (?, ?)",
        (movie_id, short_token_document(title, keywords)),
    )


def rebuild_short_index(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM movie_search_short")
    rows = conn.execute("SELECT rowid, title, keywords FROM movie_search").fetchall()
    conn.executemany(
        "INSERT INTO movie_search_short(rowid, terms) VALUES (?, ?)",
        ((row[0], short_token_document(row[1], row[2])) for row in rows),
    )
