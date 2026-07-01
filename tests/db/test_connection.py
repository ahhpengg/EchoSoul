"""Tests for the MySQL connection pool and query helpers.

These are integration tests: they require a reachable MySQL server with the
credentials in ``.env``. If the server is unreachable (e.g. CI without MySQL,
or ``.env`` still has placeholder credentials) the whole module is skipped.
"""

from __future__ import annotations

import pytest

from src.db import connection


def _db_available() -> bool:
    try:
        with connection.get_connection() as conn:
            conn.ping(reconnect=False, attempts=1)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="MySQL not reachable / .env not configured"
)


def test_fetchone_returns_dict():
    row = connection.fetchone("SELECT 1 AS one")
    assert row == {"one": 1}


def test_fetchall_returns_list_of_dicts():
    rows = connection.fetchall("SELECT 1 AS n UNION SELECT 2 AS n ORDER BY n")
    assert [r["n"] for r in rows] == [1, 2]


def test_get_cursor_rolls_back_on_error():
    # An error inside the cursor context must not leak an open transaction.
    with pytest.raises(ValueError):
        with connection.get_cursor(commit=True) as cur:
            cur.execute("SELECT 1")
            cur.fetchall()
            raise ValueError("boom")
    # Pool is still usable afterwards.
    assert connection.fetchone("SELECT 1 AS one") == {"one": 1}


def test_pool_is_singleton():
    assert connection.get_pool() is connection.get_pool()
