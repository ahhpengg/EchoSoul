"""MySQL connection pool and query helpers for the local catalogue database.

Credentials are read from the project ``.env`` (see ``.env.example``). The app
uses a small fixed-size pool and raw SQL via ``mysql-connector-python``, per
docs/DATABASE.md. There is intentionally no ORM.

All public helpers return plain ``dict`` rows (JSON-serialisable) so results can
cross the PyWebView JS bridge without conversion.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv
from mysql.connector.pooling import MySQLConnectionPool

# Load .env from the repository root regardless of the current working directory.
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

POOL_NAME = "echosoul_pool"
POOL_SIZE = 4

_pool: MySQLConnectionPool | None = None


def db_config(*, include_database: bool = True) -> dict[str, Any]:
    """Build connection kwargs from environment variables.

    Args:
        include_database: When ``False``, omit the database name so the caller
            can connect to the server before the schema exists. The migration
            bootstrap uses this to ``CREATE DATABASE`` on a fresh MySQL install.
    """
    cfg: dict[str, Any] = {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "charset": "utf8mb4",
        "collation": "utf8mb4_unicode_ci",
        "autocommit": False,
    }
    if include_database:
        cfg["database"] = os.environ.get("DB_NAME", "echosoul")
    return cfg


def get_pool() -> MySQLConnectionPool:
    """Return the process-wide connection pool, creating it on first use."""
    global _pool
    if _pool is None:
        _pool = MySQLConnectionPool(pool_name=POOL_NAME, pool_size=POOL_SIZE, **db_config())
    return _pool


@contextmanager
def get_connection() -> Iterator[Any]:
    """Acquire a pooled connection, returning it to the pool on exit.

    ``conn.close()`` on a pooled connection returns it to the pool rather than
    actually disconnecting.
    """
    conn = get_pool().get_connection()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor(*, dictionary: bool = True, commit: bool = False) -> Iterator[Any]:
    """Acquire a cursor on a pooled connection.

    Commits on clean exit when ``commit=True``; rolls back on any exception.
    """
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=dictionary)
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def fetchone(sql: str, params: tuple = ()) -> dict | None:
    """Run a query and return the first row as a dict, or ``None``."""
    with get_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetchall(sql: str, params: tuple = ()) -> list[dict]:
    """Run a query and return all rows as a list of dicts."""
    with get_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def execute(sql: str, params: tuple = (), *, commit: bool = True) -> int:
    """Run a write statement.

    Returns ``lastrowid`` for inserts with an AUTO_INCREMENT key, otherwise the
    affected ``rowcount``.
    """
    with get_cursor(commit=commit) as cur:
        cur.execute(sql, params)
        return cur.lastrowid or cur.rowcount
