"""Tests for the header-search track lookup (src/music/search.py).

The `_boolean_query` compiler is tested purely; `search_tracks` runs as an
integration test against the real ``echosoul`` database (read-only) and is
skipped if MySQL is unreachable. The catalogue-dependent assertions use words
("love") that any 1.3M-track catalogue is guaranteed to contain.
"""

from __future__ import annotations

import pytest

from src.db import connection
from src.music import search
from src.music.search import _boolean_query


def _db_available() -> bool:
    try:
        with connection.get_connection() as conn:
            conn.ping(reconnect=False, attempts=1)
        return True
    except Exception:
        return False


_DB = pytest.mark.skipif(not _db_available(), reason="MySQL not reachable / .env not configured")


# --- _boolean_query (pure) ----------------------------------------------------


def test_boolean_query_makes_every_token_a_required_prefix():
    assert _boolean_query("crazy love") == "+crazy* +love*"


def test_boolean_query_keeps_short_final_token():
    # The final token is what the user is mid-typing: "lo*" must match "love".
    assert _boolean_query("lo") == "+lo*"


def test_boolean_query_drops_short_non_final_tokens():
    # "7" is a completed word below InnoDB's indexed-token minimum (3): it can
    # never match, and as a required term it would veto the whole query.
    assert _boolean_query("7 rings") == "+rings*"


def test_boolean_query_strips_boolean_operators():
    assert _boolean_query('love" -happy @3 (rock)') == "+love* +happy* +rock*"


def test_boolean_query_returns_none_when_nothing_survives():
    assert _boolean_query("   ") is None
    assert _boolean_query('+-"~') is None
    assert _boolean_query("&& ~~") is None  # no word characters


# --- search_tracks (integration) ----------------------------------------------


@_DB
def test_search_returns_matching_rows_with_expected_keys():
    rows = search.search_tracks("love")
    assert rows, "a 1.3M-track catalogue must contain 'love' titles"
    expected = {"track_id", "track_name", "artists", "album_name", "duration_ms", "popularity"}
    assert set(rows[0]) == expected


@_DB
def test_search_results_match_query_as_word_prefix():
    for row in search.search_tracks("love"):
        haystack = f"{row['track_name']} {row['artists']}".lower()
        assert "love" in haystack


@_DB
def test_search_orders_most_popular_first():
    rows = search.search_tracks("love")
    popularity = [row["popularity"] for row in rows]
    # NULL popularity (tier-2 top-up rows) may only appear after every valued row.
    valued = [p for p in popularity if p is not None]
    assert valued == sorted(valued, reverse=True)
    if None in popularity:
        assert popularity.index(None) == len(valued)


@_DB
def test_search_matches_artist_names_too():
    rows = search.search_tracks("taylor swift")
    assert rows
    assert any("taylor swift" in row["artists"].lower() for row in rows)


@_DB
def test_search_respects_limit():
    assert len(search.search_tracks("love", limit=3)) == 3


@_DB
def test_search_short_query_returns_nothing():
    assert search.search_tracks("a") == []
    assert search.search_tracks("  ") == []


@_DB
def test_search_operator_injection_is_neutralised():
    # Must not raise a MySQL syntax error, whatever the user types.
    search.search_tracks('love" -happy @3 ~(*)')


@_DB
def test_search_unmatched_query_returns_empty():
    assert search.search_tracks("zzxqjvwk") == []


@_DB
def test_search_rejects_out_of_range_limit():
    with pytest.raises(ValueError):
        search.search_tracks("love", limit=0)
    with pytest.raises(ValueError):
        search.search_tracks("love", limit=search.MAX_LIMIT + 1)
