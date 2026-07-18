"""Tests for the canonical-genre mapping (migration 0009 + seed CSV).

The seed-CSV integrity tests always run. The schema/data assertions are
integration tests against the real ``echosoul`` database, skipped if MySQL is
unreachable, and assume ``scripts/apply_genre_mapping.py`` has been run once
(they are read-only).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.db import connection, migrate

SEED_CSV = Path(__file__).resolve().parents[2] / "data" / "seed" / "genre_canonical_map.csv"

CANONICAL_BUCKETS = {
    "Pop", "Rock", "Indie / Alternative", "Metal", "Punk / Hardcore",
    "Hip-Hop / Rap", "R&B / Soul", "Electronic / Dance", "Jazz", "Blues",
    "Classical", "Country", "Folk / Acoustic", "Latin", "Reggae", "World",
    "K-Pop", "J-Pop / Anime", "C-Pop / Mandopop", "SEA Pop",
    "Soundtrack / Musical", "Ambient / Instrumental", "Christian / Gospel",
}


def _seed_rows() -> list[dict]:
    with SEED_CSV.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# --- seed CSV integrity (no DB needed) ---------------------------------------


def test_seed_csv_has_no_duplicate_raw_tags():
    rows = _seed_rows()
    raw = [r["raw_genre"] for r in rows]
    assert len(raw) == len(set(raw))
    assert len(rows) > 3000  # the full observed-tag inventory, not a sample


def test_seed_csv_buckets_are_the_canonical_vocabulary():
    used = {r["canonical_genre"] for r in _seed_rows() if r["canonical_genre"]}
    assert used == CANONICAL_BUCKETS


def test_seed_csv_layers_are_consistent_with_buckets():
    for r in _seed_rows():
        assert r["layer"] in {"exact", "rule", "junk", "unmapped"}
        # junk/unmapped rows must stay NULL; mapped layers must name a bucket
        assert bool(r["canonical_genre"]) == (r["layer"] in {"exact", "rule"})


def test_owner_example_synonyms_collapse_to_cpop():
    by_raw = {r["raw_genre"]: r["canonical_genre"] for r in _seed_rows()}
    assert by_raw["c-pop"] == by_raw["mandopop"] == by_raw["chinese"] == "C-Pop / Mandopop"


# --- live-DB assertions -------------------------------------------------------


def _db_available() -> bool:
    try:
        migrate.ensure_database_exists()
        with connection.get_connection() as conn:
            conn.ping(reconnect=False, attempts=1)
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _db_available(), reason="MySQL not reachable / .env not configured"
)


@needs_db
def test_canonical_genre_column_and_index_exist():
    cols = connection.fetchall("SHOW COLUMNS FROM music LIKE 'canonical_genre'")
    assert len(cols) == 1
    keys = {r["Key_name"] for r in connection.fetchall("SHOW INDEX FROM music")}
    assert "idx_music_canonical_genre" in keys


@needs_db
def test_view_exposes_canonical_genre():
    row = connection.fetchone(
        "SELECT COUNT(*) AS n FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'v_in_scope_music' "
        "AND column_name = 'canonical_genre'"
    )
    assert row["n"] == 1


@needs_db
def test_backfilled_values_match_the_vocabulary():
    rows = connection.fetchall(
        "SELECT DISTINCT canonical_genre AS b FROM music WHERE canonical_genre IS NOT NULL"
    )
    assert {r["b"] for r in rows} == CANONICAL_BUCKETS


@needs_db
def test_null_raw_genre_rows_stay_null():
    row = connection.fetchone(
        "SELECT COUNT(*) AS n FROM music WHERE genre IS NULL AND canonical_genre IS NOT NULL"
    )
    assert row["n"] == 0
