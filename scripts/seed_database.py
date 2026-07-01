"""Stage 5 of the music-data pipeline: load music_merged.csv into `music`.

Bulk-loads via chunked multi-row INSERT (portable — no LOAD DATA LOCAL INFILE
server config required). Drops the three music indexes before loading and
recreates them afterwards, which is far faster than maintaining them during a
~1.2M-row insert (docs/DATABASE.md). The rule table and playlists are untouched.

Safety: refuses to run if `music` already has rows unless --confirm is given
(re-seeding wipes and reloads the catalogue).

Run:
    python scripts/seed_database.py            # first load
    python scripts/seed_database.py --confirm  # re-seed over existing data
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.connection import db_config  # noqa: E402
import mysql.connector  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MERGED = ROOT / "data" / "processed" / "music_merged.csv"

MUSIC_COLUMNS = [
    "track_id",
    "track_name",
    "artists",
    "artist_ids",
    "album_name",
    "genre",
    "genre_source",
    "valence",
    "energy",
    "tempo",
    "popularity",
    "duration_ms",
    "release_year",
]
INT_COLUMNS = {"popularity", "duration_ms", "release_year"}
INDEXES = {
    "idx_music_vet": "CREATE INDEX idx_music_vet ON music (valence, energy, tempo)",
    "idx_music_genre": "CREATE INDEX idx_music_genre ON music (genre)",
    "idx_music_popularity": "CREATE INDEX idx_music_popularity ON music (popularity)",
}
CHUNK = 10_000


def _index_names(cursor) -> set[str]:
    cursor.execute("SHOW INDEX FROM music")
    return {row[2] for row in cursor.fetchall()}  # Key_name is column 2


def drop_indexes(cursor) -> None:
    present = _index_names(cursor)
    for name in INDEXES:
        if name in present:
            cursor.execute(f"DROP INDEX {name} ON music")
            print(f"dropped index {name}")


def create_indexes(cursor) -> None:
    present = _index_names(cursor)
    for name, ddl in INDEXES.items():
        if name not in present:
            print(f"creating index {name} ...")
            cursor.execute(ddl)


def _chunk_to_rows(chunk: pd.DataFrame) -> list[tuple]:
    chunk = chunk[MUSIC_COLUMNS].copy()
    for col in INT_COLUMNS:
        chunk[col] = pd.to_numeric(chunk[col], errors="coerce").astype("Int64")
    rows: list[tuple] = []
    for record in chunk.itertuples(index=False, name=None):
        row = []
        for value in record:
            if value is pd.NA or (isinstance(value, float) and pd.isna(value)):
                row.append(None)
            elif isinstance(value, np.integer):
                row.append(int(value))
            else:
                row.append(value)
        rows.append(tuple(row))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the music catalogue")
    parser.add_argument("--confirm", action="store_true", help="wipe and reload if non-empty")
    args = parser.parse_args()

    if not MERGED.exists():
        sys.exit(f"{MERGED} not found; run merge_catalogues.py first")

    conn = mysql.connector.connect(**db_config())
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM music")
    existing = cursor.fetchone()[0]
    if existing and not args.confirm:
        sys.exit(f"music already has {existing:,} rows; re-run with --confirm to wipe and reload")

    if existing:
        print(f"wiping {existing:,} existing rows ...")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute("DELETE FROM music")  # TRUNCATE is blocked by the FK
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()

    drop_indexes(cursor)
    conn.commit()

    placeholders = ", ".join(["%s"] * len(MUSIC_COLUMNS))
    insert_sql = f"INSERT INTO music ({', '.join(MUSIC_COLUMNS)}) VALUES ({placeholders})"

    total = 0
    for chunk in pd.read_csv(MERGED, chunksize=CHUNK):
        cursor.executemany(insert_sql, _chunk_to_rows(chunk))
        conn.commit()
        total += len(chunk)
        print(f"  inserted {total:,} rows", flush=True)

    print("rebuilding indexes (this is the slow part) ...")
    create_indexes(cursor)
    conn.commit()
    cursor.close()
    conn.close()
    print(f"seeded {total:,} tracks into music.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
