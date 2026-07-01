"""Stage 2 of the music-data pipeline: normalise each source CSV.

Reads the three canonical CSVs from data/raw/ (produced by
download_datasets.py) and writes one normalised CSV per source into
data/processed/, all sharing the unified schema in docs/MUSIC_DATA.md.

Deviation from the doc: the rodolfofigueroa file (tracks_features.csv) has no
``popularity`` column, so popularity is left NA for that source.

Run:
    python scripts/normalise_datasets.py
"""

from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
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


def _parse_list_str(value):
    """Parse a Python list-literal string (rodolfofigueroa's artists/artist_ids).

    e.g. "['Drake', 'Future']" -> "Drake;Future". Falls back to the raw value
    if it is not a parseable list literal.
    """
    if not isinstance(value, str):
        return pd.NA
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value
    if isinstance(parsed, (list, tuple)):
        return ";".join(str(item) for item in parsed)
    return str(parsed)


def normalise_maharshipandya() -> pd.DataFrame:
    df = pd.read_csv(RAW / "maharshipandya_spotify_tracks.csv")
    return pd.DataFrame(
        {
            "track_id": df["track_id"],
            "track_name": df["track_name"],
            "artists": df["artists"],  # already ;-separated in source
            "artist_ids": pd.NA,
            "album_name": df["album_name"],
            "genre": df["track_genre"],
            "genre_source": "mh",
            "valence": df["valence"],
            "energy": df["energy"],
            "tempo": df["tempo"],
            "popularity": df["popularity"],
            "duration_ms": df["duration_ms"],
            "release_year": pd.NA,
        }
    )


def normalise_joebeachcapital() -> pd.DataFrame:
    df = pd.read_csv(RAW / "joebeachcapital_30k_songs.csv")
    # Keep the highest-popularity row per track_id (source has playlist dupes).
    df = df.sort_values("track_popularity", ascending=False).drop_duplicates("track_id")
    genre = df["playlist_subgenre"].fillna(df["playlist_genre"])
    genre_source = (
        df["playlist_subgenre"].notna().map(lambda has_sub: "jbc_sub" if has_sub else "jbc")
    )
    return pd.DataFrame(
        {
            "track_id": df["track_id"],
            "track_name": df["track_name"],
            "artists": df["track_artist"],
            "artist_ids": pd.NA,
            "album_name": df["track_album_name"],
            "genre": genre,
            "genre_source": genre_source,
            "valence": df["valence"],
            "energy": df["energy"],
            "tempo": df["tempo"],
            "popularity": df["track_popularity"],
            "duration_ms": df["duration_ms"],
            "release_year": pd.to_datetime(df["track_album_release_date"], errors="coerce").dt.year,
        }
    )


def normalise_rodolfofigueroa() -> pd.DataFrame:
    use_cols = [
        "id",
        "name",
        "album",
        "artists",
        "artist_ids",
        "valence",
        "energy",
        "tempo",
        "duration_ms",
        "year",
    ]
    df = pd.read_csv(RAW / "rodolfofigueroa_12m_songs.csv", usecols=use_cols)
    return pd.DataFrame(
        {
            "track_id": df["id"],
            "track_name": df["name"],
            "artists": df["artists"].apply(_parse_list_str),
            "artist_ids": df["artist_ids"].apply(_parse_list_str),  # critical for enrichment
            "album_name": df["album"],
            "genre": pd.NA,  # filled in stage 3 (artist-genre enrichment)
            "genre_source": pd.NA,
            "valence": df["valence"],
            "energy": df["energy"],
            "tempo": df["tempo"],
            "popularity": pd.NA,  # not present in this dataset
            "duration_ms": df["duration_ms"],
            "release_year": pd.to_numeric(df["year"], errors="coerce"),
        }
    )


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("maharshipandya", normalise_maharshipandya, "mh_normalised.csv"),
        ("joebeachcapital", normalise_joebeachcapital, "jbc_normalised.csv"),
        ("rodolfofigueroa", normalise_rodolfofigueroa, "rf_normalised.csv"),
    ]
    for name, fn, out_name in jobs:
        print(f"normalising {name} ...")
        df = fn()[UNIFIED_COLUMNS]
        out_path = PROCESSED / out_name
        df.to_csv(out_path, index=False)
        print(f"  -> {out_name}: {len(df):,} rows")


if __name__ == "__main__":
    main()
