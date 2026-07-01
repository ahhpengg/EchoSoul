"""Stage 4 of the music-data pipeline: merge the three normalised CSVs.

Concatenates mh + jbc + rf (in that priority order), resolves each
rodolfofigueroa track's genre from the Last.fm artist-genre map, dedupes on
track_id keeping the highest-priority source, applies sanity filters, and
writes data/processed/music_merged.csv.

Genre priority (encoded by concat order + keep="first"):
    maharshipandya track_genre > joebeachcapital sub/genre > rf artist genre.

Re-runnable: overwrites music_merged.csv. Re-run after the Last.fm enrichment
finishes to pick up the fuller artist_genres.csv.

Run:
    python scripts/merge_catalogues.py
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pandas as pd

# A plausible genre label: starts with a letter, 2-30 chars of letters/digits/
# spaces and a few genre punctuation marks (e.g. "hip-hop", "r&b", "drum & bass",
# "contemporary classical"). Rejects freeform Last.fm junk tags such as "<3",
# "-artist", ":51n7h3515:", "11", or 100-char concatenations.
_VALID_GENRE = re.compile(r"^[a-z][a-z0-9 &/+'-]{1,29}$")


def is_valid_genre(tag: str) -> bool:
    return _VALID_GENRE.match(tag) is not None


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"

UNIFIED_COLUMNS = [
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


def load_artist_genre_map(path: Path) -> dict[str, list[str]]:
    """artist_id -> [genres] from the enrichment output (may be partial)."""
    if not path.exists():
        print("[warn] artist_genres.csv not found; rodolfofigueroa tracks get NULL genre")
        return {}
    # on_bad_lines='skip' guards against a partial last line if enrichment is
    # still appending concurrently.
    df = pd.read_csv(path, usecols=["artist_id", "genres"], on_bad_lines="skip")
    mapping: dict[str, list[str]] = {}
    for aid, genres in zip(df["artist_id"], df["genres"].fillna("")):
        mapping[str(aid)] = [g for g in str(genres).split(";") if g and is_valid_genre(g)]
    return mapping


def resolve_track_genre(artist_ids: list[str], artist_map: dict[str, list[str]]) -> str | None:
    """Most common genre across a track's artists; None if none are known."""
    all_genres: list[str] = []
    for aid in artist_ids:
        all_genres.extend(artist_map.get(aid, []))
    if not all_genres:
        return None
    return Counter(all_genres).most_common(1)[0][0]


def merge() -> pd.DataFrame:
    mh = pd.read_csv(PROCESSED / "mh_normalised.csv")
    jbc = pd.read_csv(PROCESSED / "jbc_normalised.csv")
    rf = pd.read_csv(PROCESSED / "rf_normalised.csv")

    artist_map = load_artist_genre_map(PROCESSED / "artist_genres.csv")
    print(f"artist-genre map: {len(artist_map):,} artists with genres")

    def resolve(ids) -> str | None:
        id_list = str(ids).split(";") if pd.notna(ids) else []
        return resolve_track_genre(id_list, artist_map)

    rf["genre"] = rf["artist_ids"].apply(resolve)
    rf["genre_source"] = rf["genre"].notna().map(lambda has: "artist" if has else pd.NA)

    combined = pd.concat([mh, jbc, rf], ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(subset="track_id", keep="first")
    print(f"concatenated {before:,} rows -> {len(combined):,} unique track_ids")

    # Sanity filters (also done defensively in the v_in_scope_music view).
    combined = combined[
        combined["valence"].between(0, 1)
        & combined["energy"].between(0, 1)
        & combined["tempo"].between(20, 250)
    ]
    combined = combined[combined["track_id"].astype(str).str.len() == 22]

    # The music table declares track_name and artists NOT NULL; drop rows
    # missing either (unusable for display anyway).
    not_null = combined["track_name"].notna() & combined["artists"].notna()
    dropped = (~not_null).sum()
    if dropped:
        print(f"dropped {dropped:,} rows with null track_name/artists")
    combined = combined[not_null].copy()

    # Fit the VARCHAR limits from docs/DATABASE.md so the bulk insert can't
    # overflow a column (long titles / many-artist classical compilations).
    for col, limit in {"track_name": 500, "artists": 500, "album_name": 500, "genre": 100}.items():
        mask = combined[col].notna()
        combined.loc[mask, col] = combined.loc[mask, col].astype(str).str.slice(0, limit)
    # artist_ids: truncate on a ';' boundary so the remaining IDs stay valid.
    ai_mask = combined["artist_ids"].notna()
    combined.loc[ai_mask, "artist_ids"] = (
        combined.loc[ai_mask, "artist_ids"]
        .astype(str)
        .map(lambda s: s if len(s) <= 500 else s[:500].rsplit(";", 1)[0])
    )

    combined = combined[UNIFIED_COLUMNS]
    out_path = PROCESSED / "music_merged.csv"
    combined.to_csv(out_path, index=False)

    print(f"\nFinal catalogue: {len(combined):,} tracks -> {out_path.name}")
    print("genre_source breakdown:")
    print(combined["genre_source"].value_counts(dropna=False).to_string())
    genre_pct = combined["genre"].notna().mean() * 100
    print(f"tracks with a genre: {genre_pct:.1f}%")
    return combined


if __name__ == "__main__":
    merge()
