"""Stage 1 of the music-data pipeline: get the three source CSVs into data/raw/.

The maintainer downloads three Kaggle/Hugging Face datasets (as ``.zip``
archives) into ``data/raw/``. This script extracts each archive's CSV to a
canonical filename so the rest of the pipeline can rely on fixed paths.

Datasets are identified by their *columns*, not by the (arbitrary) zip name, so
``archive (3).zip`` etc. are handled fine. Idempotent: a canonical CSV that
already exists is left untouched.

Canonical outputs (docs/MUSIC_DATA.md):
    data/raw/maharshipandya_spotify_tracks.csv   dataset 1 (has track_genre)
    data/raw/joebeachcapital_30k_songs.csv       dataset 2 (playlist genres)
    data/raw/rodolfofigueroa_12m_songs.csv       dataset 3 (~1.2M, no genre)

If a dataset is missing, prints where to download it. Run:
    python scripts/download_datasets.py
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

TARGETS = {
    "maharshipandya": RAW_DIR / "maharshipandya_spotify_tracks.csv",
    "joebeachcapital": RAW_DIR / "joebeachcapital_30k_songs.csv",
    "rodolfofigueroa": RAW_DIR / "rodolfofigueroa_12m_songs.csv",
}

DOWNLOAD_HINTS = {
    "maharshipandya": "https://huggingface.co/datasets/maharshipandya/spotify-tracks-dataset",
    "joebeachcapital": "https://www.kaggle.com/datasets/joebeachcapital/30000-spotify-songs",
    "rodolfofigueroa": "https://www.kaggle.com/datasets/rodolfofigueroa/spotify-12m-songs",
}


def classify(columns: set[str]) -> str | None:
    """Identify which source a CSV is, from its header columns."""
    if "track_genre" in columns:
        return "maharshipandya"
    if "playlist_subgenre" in columns:
        return "joebeachcapital"
    if "artist_ids" in columns and "id" in columns:
        return "rodolfofigueroa"
    return None


def _header_columns(first_line: bytes) -> set[str]:
    return {c.strip() for c in first_line.decode("utf-8", "replace").strip().split(",")}


def extract_all() -> dict[str, Path]:
    """Extract recognised CSVs from any zips in data/raw/ to canonical names."""
    found: dict[str, Path] = {}
    for name, target in TARGETS.items():
        if target.exists():
            found[name] = target
            print(f"[skip]    {name}: {target.name} already present")

    for zip_path in sorted(RAW_DIR.glob("*.zip")):
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                if not member.filename.lower().endswith(".csv"):
                    continue
                with zf.open(member.filename) as handle:
                    dataset = classify(_header_columns(handle.readline()))
                if dataset is None:
                    print(f"[warn]    {zip_path.name}:{member.filename} unrecognised, skipping")
                    continue
                if dataset in found:
                    continue
                target = TARGETS[dataset]
                print(f"[extract] {zip_path.name}:{member.filename} -> {target.name}")
                with zf.open(member.filename) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)  # stream-copy (handles the 329 MB file)
                found[dataset] = target
    return found


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    found = extract_all()
    missing = [name for name in TARGETS if name not in found]
    if missing:
        print("\nMissing datasets:", ", ".join(missing))
        print("Download each (as .zip) into data/raw/ and re-run:")
        for name in missing:
            print(f"  {name}: {DOWNLOAD_HINTS[name]}")
        return 1
    print("\nAll three source CSVs are present in data/raw/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
