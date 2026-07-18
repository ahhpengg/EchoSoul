"""Backfill music.canonical_genre from the committed genre mapping.

Reads data/seed/genre_canonical_map.csv (the owner-reviewed raw-tag ->
canonical-bucket mapping, docs/DATABASE.md "Canonical genre") and populates the
`canonical_genre` column added by migration 0009. Junk/unmapped rows in the CSV
have an empty `canonical_genre` and are left NULL, as are rows whose raw
`genre` is NULL (external tracks included).

Idempotent reset-then-apply: the column is cleared first, so the end state is a
pure function of the CSV and the current catalogue. Re-run after editing the
mapping or re-seeding the catalogue. Runtime is a couple of minutes locally;
interrupting mid-run is harmless (just run it again).

Usage:
    python scripts/apply_genre_mapping.py
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.connection import get_connection  # noqa: E402

SEED_CSV = Path(__file__).resolve().parents[1] / "data" / "seed" / "genre_canonical_map.csv"

# Commit granularity: bounds transaction size while keeping overhead negligible.
TAGS_PER_COMMIT = 100


def load_mapping(path: Path) -> dict[str, str]:
    """Return {raw_genre: canonical_genre} for the mapped rows of the seed CSV.

    Raises ValueError on structural problems (duplicate raw tags, over-length
    bucket names) — the CSV is committed source of truth, so fail loud.
    """
    mapping: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for rec in csv.DictReader(fh):
            raw, canonical = rec["raw_genre"], rec["canonical_genre"]
            if raw in mapping:
                raise ValueError(f"duplicate raw_genre in seed CSV: {raw!r}")
            mapping[raw] = canonical
            if len(canonical) > 50:
                raise ValueError(f"canonical_genre over VARCHAR(50): {canonical!r}")
    return {raw: canonical for raw, canonical in mapping.items() if canonical}


def apply_mapping(mapping: dict[str, str]) -> int:
    """Reset the column, then set it per raw tag. Returns total rows updated."""
    started = time.monotonic()
    total = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE music SET canonical_genre = NULL WHERE canonical_genre IS NOT NULL")
        conn.commit()
        print(f"reset {cursor.rowcount:,} previously-set rows")

        for i, (raw, canonical) in enumerate(sorted(mapping.items()), 1):
            cursor.execute(
                "UPDATE music SET canonical_genre = %s WHERE genre = %s", (canonical, raw)
            )
            total += cursor.rowcount
            if i % TAGS_PER_COMMIT == 0:
                conn.commit()
                print(f"  {i:,}/{len(mapping):,} tags applied ({total:,} rows)")
        conn.commit()
        cursor.close()
    print(f"done: {len(mapping):,} tags -> {total:,} rows in {time.monotonic() - started:.0f}s")
    return total


def print_bucket_counts() -> None:
    """Show the resulting per-bucket row counts for eyeball verification."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT canonical_genre, COUNT(*) FROM music "
            "WHERE canonical_genre IS NOT NULL "
            "GROUP BY canonical_genre ORDER BY COUNT(*) DESC"
        )
        for bucket, n in cursor.fetchall():
            print(f"  {bucket:<24} {n:>9,}")
        cursor.close()


def main() -> None:
    mapping = load_mapping(SEED_CSV)
    print(f"loaded {len(mapping):,} mapped tags from {SEED_CSV.name}")
    apply_mapping(mapping)
    print_bucket_counts()


if __name__ == "__main__":
    main()
