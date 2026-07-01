"""Idempotent migration runner for the local MySQL catalogue database.

Applies numbered ``.sql`` files in ``src/db/migrations/`` in order, recording
each applied version in a ``schema_version`` table so re-runs are no-ops. Run at
app startup; a failure here is fatal — the app must not start on a broken
schema (docs/DATABASE.md).

Usage:
    python -m src.db.migrate
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import mysql.connector

from src.db.connection import db_config, get_connection

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def ensure_database_exists() -> None:
    """Create the target database if it does not yet exist.

    Connects to the server *without* selecting a database so this works on a
    fresh MySQL install where ``echosoul`` has not been created yet.
    """
    name = os.environ.get("DB_NAME", "echosoul")
    conn = mysql.connector.connect(**db_config(include_database=False))
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.commit()
        cursor.close()
    finally:
        conn.close()


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into individual statements.

    Strips ``--`` line comments and splits on ``;``. Our migration files use
    ``;`` only as a statement terminator — no stored routines and no semicolons
    inside string literals — so this simple splitter is sufficient. Do not add
    such constructs without revisiting this function.
    """
    kept = [line for line in sql.splitlines() if line.strip() and not line.strip().startswith("--")]
    body = "\n".join(kept)
    return [stmt.strip() for stmt in body.split(";") if stmt.strip()]


def _discover_migrations() -> list[tuple[int, Path]]:
    """Return ``(version, path)`` for every migration, ordered by version."""
    migrations = []
    for path in MIGRATIONS_DIR.glob("*.sql"):
        version = int(path.name.split("_", 1)[0])
        migrations.append((version, path))
    return sorted(migrations)


def _applied_versions(cursor) -> set[int]:
    """Ensure the ``schema_version`` table exists and return applied versions."""
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version    INT NOT NULL PRIMARY KEY,"
        "  filename   VARCHAR(255) NOT NULL,"
        "  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
    )
    cursor.execute("SELECT version FROM schema_version")
    return {row[0] for row in cursor.fetchall()}


def run_migrations() -> list[int]:
    """Apply all pending migrations in order. Returns the versions applied."""
    ensure_database_exists()
    applied: list[int] = []
    with get_connection() as conn:
        cursor = conn.cursor()
        existing = _applied_versions(cursor)
        for version, path in _discover_migrations():
            if version in existing:
                continue
            for statement in _split_statements(path.read_text(encoding="utf-8")):
                cursor.execute(statement)
            cursor.execute(
                "INSERT INTO schema_version (version, filename) VALUES (%s, %s)",
                (version, path.name),
            )
            conn.commit()
            applied.append(version)
            print(f"applied migration {path.name}")
        cursor.close()
    if not applied:
        print("database is up to date; no migrations applied")
    return applied


if __name__ == "__main__":
    try:
        run_migrations()
    except Exception as exc:  # noqa: BLE001 - fatal: surface any failure clearly
        print(f"FATAL: migration failed: {exc}", file=sys.stderr)
        sys.exit(1)
