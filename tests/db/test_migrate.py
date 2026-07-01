"""Tests for the migration runner.

Integration tests against the real ``echosoul`` database. Assumes
migrations have been applied at least once (``python -m src.db.migrate``).
Skipped if MySQL is unreachable. All assertions are read-only or rely on the
idempotency of the runner, so running them does not mutate real data.
"""

from __future__ import annotations

import pytest

from src.db import connection, migrate


def _db_available() -> bool:
    try:
        migrate.ensure_database_exists()
        with connection.get_connection() as conn:
            conn.ping(reconnect=False, attempts=1)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="MySQL not reachable / .env not configured"
)


@pytest.fixture(scope="module", autouse=True)
def _migrated():
    """Ensure the schema is present before assertions run."""
    migrate.run_migrations()


def test_running_again_is_a_noop():
    # Already migrated by the fixture, so a second run applies nothing.
    assert migrate.run_migrations() == []


def test_all_tables_exist():
    rows = connection.fetchall("SHOW TABLES")
    names = {next(iter(r.values())) for r in rows}
    assert {"music", "emotion_music_mapping", "playlist", "playlist_song"} <= names


def test_in_scope_view_exists():
    row = connection.fetchone(
        "SELECT COUNT(*) AS n FROM information_schema.views "
        "WHERE table_schema = DATABASE() AND table_name = 'v_in_scope_music'"
    )
    assert row["n"] == 1


def test_emotion_mapping_seeded_with_five_rows():
    row = connection.fetchone("SELECT COUNT(*) AS n FROM emotion_music_mapping")
    assert row["n"] == 5


def test_happy_rule_matches_seed_values():
    rule = connection.fetchone(
        "SELECT valence_min, valence_max, energy_min, energy_max, tempo_min, tempo_max "
        "FROM emotion_music_mapping WHERE emotion = %s",
        ("happy",),
    )
    assert rule["valence_min"] == pytest.approx(0.66)
    assert rule["tempo_max"] == pytest.approx(250.0)


def test_indexes_present_on_music():
    rows = connection.fetchall("SHOW INDEX FROM music")
    key_names = {r["Key_name"] for r in rows}
    assert {"idx_music_vet", "idx_music_genre", "idx_music_popularity"} <= key_names


def test_schema_version_records_three_migrations():
    row = connection.fetchone("SELECT COUNT(*) AS n FROM schema_version")
    assert row["n"] >= 3
