"""Catalogue track search for the header search bar.

FULLTEXT word-prefix search, most popular first — see docs/DATABASE.md
§ "Track search". The user's free text is compiled into a BOOLEAN MODE
expression where every word is a required prefix match (``+word*``), so
"crazy lo" finds "Crazy in Love".

Two-tier query plan (both tiers use the same expression):

1. ``music_search_hot`` (migration 0007) — the ~116k catalogue rows that have
   a popularity value, ordered by popularity. Popularity-ordered results can
   only come from this slice (NULL popularity sorts last), and the table is
   small enough that even the broadest prefix answers in tens of ms. The
   naive single-table query was measured at 3-9 s for broad prefixes: MySQL
   fetches every FULLTEXT match (34k+ rows) to read ``popularity``, on a
   table far bigger than the default InnoDB buffer pool.
2. If tier 1 cannot fill the limit, top up from the full ``music`` FULLTEXT
   index (migration 0006) ordered by relevance — InnoDB's rank-sort fast
   path, which never materialises the whole match set. The tracks reached
   only here have no popularity data, so best-text-match is the honest order
   for them.
"""

from __future__ import annotations

import re

from src.db import connection

# Queries shorter than this return no results (the frontend enforces the same
# floor before calling); one character matches absurdly broad prefixes.
MIN_QUERY_LENGTH = 2

# Upper bound on rows a single search may request (the dropdown shows 10).
MAX_LIMIT = 50

# Characters with operator meaning inside a BOOLEAN MODE expression, stripped
# from user input so a stray '-' or '"' cannot change the query semantics.
_BOOLEAN_OPERATORS = re.compile(r'[+\-<>()~*"@]')

# InnoDB only indexes words of at least innodb_ft_min_token_size (default 3)
# characters, so a short *completed* word ("7" in "7 rings") can never match
# and, as a required +term, would veto the whole query — drop short non-final
# tokens. The final token is whatever the user is still typing and is kept at
# any length: short *prefixes* of indexed words ("lo*" -> "love") do match.
_MIN_INDEXED_TOKEN = 3

# Tokens must contain at least one word character; a token of pure punctuation
# ("&&") would otherwise produce a malformed boolean term.
_HAS_WORD_CHAR = re.compile(r"\w")

# Tier 1: the popularity-valued slice, true popularity order. The whole match
# set is fetched and sorted, but the table is ~116k slim rows so that's cheap.
_HOT_SQL = """
    SELECT track_id, track_name, artists, album_name, duration_ms, popularity
    FROM music_search_hot
    WHERE MATCH(track_name, artists) AGAINST (%s IN BOOLEAN MODE)
    ORDER BY popularity DESC, track_name
    LIMIT %s
"""

# Tier 2 top-up: full catalogue by relevance. ORDER BY the MATCH expression
# DESC + LIMIT triggers InnoDB's early-terminating rank-sort optimisation, so
# this stays fast even when the expression matches 100k docs.
_TAIL_SQL = """
    SELECT track_id, track_name, artists, album_name, duration_ms, popularity
    FROM music
    WHERE MATCH(track_name, artists) AGAINST (%s IN BOOLEAN MODE)
    ORDER BY MATCH(track_name, artists) AGAINST (%s IN BOOLEAN MODE) DESC
    LIMIT %s
"""


def _boolean_query(query: str) -> str | None:
    """Compile free text into a safe BOOLEAN MODE expression, or None if empty.

    Every kept token becomes a required prefix match (``+token*``): all typed
    words must appear as word prefixes somewhere in the title or artists.
    """
    stripped = _BOOLEAN_OPERATORS.sub(" ", query)
    tokens = [t for t in stripped.split() if _HAS_WORD_CHAR.search(t)]
    if not tokens:
        return None
    kept = [t for t in tokens[:-1] if len(t) >= _MIN_INDEXED_TOKEN]
    kept.append(tokens[-1])
    return " ".join(f"+{token}*" for token in kept)


def search_tracks(query: str, limit: int = 10) -> list[dict]:
    """Search the catalogue by track title / artist name.

    Args:
        query: Free text from the search box, word-prefix semantics ("lov"
               finds "Love Story"). Shorter than MIN_QUERY_LENGTH returns [].
        limit: Maximum rows to return, 1..MAX_LIMIT.

    Returns catalogue rows (track_id, track_name, artists, album_name,
    duration_ms, popularity) ordered most-popular first. Raises ValueError for
    a limit outside the allowed range.
    """
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}, got {limit}")
    if len(query.strip()) < MIN_QUERY_LENGTH:
        return []
    expression = _boolean_query(query)
    if expression is None:
        return []

    rows = connection.fetchall(_HOT_SQL, (expression, limit))
    if len(rows) < limit:
        # The hot tier was NOT truncated, so `seen` is every popularity-valued
        # match; anything new the tail returns has NULL popularity. Over-fetch
        # by len(seen) because those seen rows may occupy the tail's top spots.
        seen = {row["track_id"] for row in rows}
        deficit = limit - len(rows)
        tail = connection.fetchall(_TAIL_SQL, (expression, expression, deficit + len(seen)))
        rows += [row for row in tail if row["track_id"] not in seen][:deficit]
    return rows
