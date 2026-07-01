"""Stage 3 of the music-data pipeline: artist-genre enrichment via Last.fm.

WHY NOT SPOTIFY: Spotify removed artist genres for post-Nov-2024 apps. For this
app the artist object has no `genres` field at all (verified) and the batch
GET /artists?ids=... endpoint returns 403. So Spotify cannot supply genres.

INSTEAD: Last.fm's `artist.getTopTags` returns crowd tags whose top entries are
a usable genre proxy. Last.fm is keyed by artist NAME, so we read the parallel
artists / artist_ids columns from rf_normalised.csv, look each artist up by
name, and write rows keyed by artist_id so merge_catalogues.py can map
track -> genre unchanged.

Artists are processed in descending track-count order so the most impactful
genres fill first. Resumable (skips artist_ids already written), checkpointed,
rate-limited, and Ctrl+C-clean. Coverage: top 50k artists ~= 88% of tracks,
top 100k ~= 98%.

Needs LASTFM_API_KEY in .env (free: https://www.last.fm/api/account/create).
No extra pip dependency beyond requests.

Usage:
    python scripts/enrich_artist_genres.py                 # resume, all artists
    python scripts/enrich_artist_genres.py --limit 50000   # only top-N by track count
    python scripts/enrich_artist_genres.py --force         # ignore checkpoint, restart
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import signal
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

RF_NORMALISED = ROOT / "data" / "processed" / "rf_normalised.csv"
OUTPUT = ROOT / "data" / "processed" / "artist_genres.csv"

API_URL = "http://ws.audioscrobbler.com/2.0/"
MIN_INTERVAL = 0.25  # seconds between requests (~4/s, under Last.fm's 5/s cap)
CHECKPOINT_EVERY = 500  # flush to disk every N artists
TOP_TAGS_KEPT = 3  # store up to this many genre tags per artist
OUTPUT_COLUMNS = ["artist_id", "genres", "name", "enriched_at"]

# Last.fm top tags are noisy; drop obvious non-genre tags.
_TAG_BLOCKLIST = {
    "seen live",
    "favorites",
    "favourites",
    "favorite",
    "favourite",
    "favorite songs",
    "favourite songs",
    "love",
    "loved",
    "beautiful",
    "awesome",
    "amazing",
    "spotify",
    "good",
    "best",
    "cool",
    "male vocalists",
    "female vocalists",
    "male vocalist",
    "female vocalist",
    "singer-songwriter",
    "albums i own",
    "my music",
}
_DECADE_OR_YEAR = re.compile(r"^(\d{2}s|\d{4}s|\d{4})$")  # 80s, 1990s, 2007 ...

_stop_requested = False


def _handle_sigint(signum, frame) -> None:
    global _stop_requested
    _stop_requested = True
    print("\n[signal] stop requested; will flush and exit after the current artist.")


def _clean_tags(tags: list[str]) -> list[str]:
    kept: list[str] = []
    for tag in tags:
        low = tag.strip().lower()
        if not low or low in _TAG_BLOCKLIST or _DECADE_OR_YEAR.match(low):
            continue
        kept.append(low)
        if len(kept) >= TOP_TAGS_KEPT:
            break
    return kept


def build_artist_index() -> tuple[dict[str, str], list[str]]:
    """Return (artist_id -> name) and artist_ids ordered by descending track count."""
    id_to_name: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for chunk in pd.read_csv(RF_NORMALISED, usecols=["artists", "artist_ids"], chunksize=200_000):
        for ids, names in zip(chunk["artist_ids"].fillna(""), chunk["artists"].fillna("")):
            id_list = [x for x in str(ids).split(";") if x]
            name_list = [y for y in str(names).split(";") if y]
            for idx, aid in enumerate(id_list):
                counts[aid] += 1
                if aid not in id_to_name and idx < len(name_list):
                    id_to_name[aid] = name_list[idx]
    ordered = [aid for aid, _ in counts.most_common()]
    return id_to_name, ordered


def load_done_artist_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done: set[str] = set()
    for chunk in pd.read_csv(path, usecols=["artist_id"], chunksize=200_000):
        done.update(chunk["artist_id"].astype(str))
    return done


class RateLimiter:
    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


def fetch_top_tags(
    session: requests.Session, api_key: str, name: str, limiter: RateLimiter
) -> list[str]:
    """Return cleaned genre tags for an artist name, or [] if none/unknown."""
    params = {
        "method": "artist.gettoptags",
        "artist": name,
        "api_key": api_key,
        "autocorrect": "1",
        "format": "json",
    }
    for attempt in range(5):
        if _stop_requested:
            return []
        limiter.wait()
        try:
            resp = session.get(API_URL, params=params, timeout=15)
        except requests.RequestException as exc:
            print(f"[net] {name!r}: {exc}; backoff")
            time.sleep(2**attempt)
            continue
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "5")) + 1
            print(f"[429] sleeping {wait}s")
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            time.sleep(2**attempt)
            continue
        try:
            data = resp.json()
        except ValueError:
            return []
        if "error" in data:
            # 6 = not found, 29 = rate limit; others: skip this artist
            if data["error"] == 29:
                time.sleep(5)
                continue
            return []
        tags = [t["name"] for t in data.get("toptags", {}).get("tag", [])]
        return _clean_tags(tags)
    return []


def append_rows(path: Path, rows: list[dict]) -> bool:
    """Append rows, retrying transient Windows file locks (e.g. antivirus scan).

    Returns True on success. On persistent failure returns False so the caller
    can keep the buffer and retry at the next checkpoint instead of losing it.
    """
    if not rows:
        return True
    write_header = not path.exists()
    for attempt in range(6):
        try:
            with open(path, "a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
                if write_header:
                    writer.writeheader()
                writer.writerows(rows)
            return True
        except PermissionError:
            if attempt == 5:
                print("[warn] checkpoint write failed (file locked); keeping buffer for next flush")
                return False
            time.sleep(1 + attempt)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Last.fm artist-genre enrichment")
    parser.add_argument("--limit", type=int, default=None, help="enrich only the top-N artists")
    parser.add_argument("--force", action="store_true", help="ignore checkpoint, start over")
    args = parser.parse_args()

    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        sys.exit(
            "LASTFM_API_KEY missing from .env (get one at https://www.last.fm/api/account/create)"
        )

    # Graceful Ctrl+C when interactive; ignore stray console signals when run
    # detached/in the background so a long run isn't killed by accident.
    if sys.stdin is not None and sys.stdin.isatty():
        signal.signal(signal.SIGINT, _handle_sigint)
    else:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    if args.force and OUTPUT.exists():
        OUTPUT.unlink()
        print("[force] removed existing checkpoint")

    print("indexing artists by track count ...")
    id_to_name, ordered = build_artist_index()
    if args.limit:
        ordered = ordered[: args.limit]
    done = load_done_artist_ids(OUTPUT)
    todo = [aid for aid in ordered if aid not in done]
    print(f"{len(ordered):,} target artists; {len(done):,} already done; {len(todo):,} remaining")
    if not todo:
        print("nothing to do.")
        return 0

    session = requests.Session()
    limiter = RateLimiter(MIN_INTERVAL)
    name_cache: dict[str, list[str]] = {}
    buffer: list[dict] = []
    started = time.time()

    for i, aid in enumerate(todo, start=1):
        if _stop_requested:
            break
        name = id_to_name.get(aid, "")
        if not name:
            continue
        if name in name_cache:
            tags = name_cache[name]
        else:
            tags = fetch_top_tags(session, api_key, name, limiter)
            name_cache[name] = tags
        buffer.append(
            {
                "artist_id": aid,
                "genres": ";".join(tags),
                "name": name,
                "enriched_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if i % CHECKPOINT_EVERY == 0:
            if append_rows(OUTPUT, buffer):
                buffer.clear()
            elapsed = time.time() - started
            rate = i / elapsed if elapsed else 0
            eta_min = (len(todo) - i) / rate / 60 if rate else 0
            print(
                f"checkpoint {i:,}/{len(todo):,} ({i/len(todo)*100:.1f}%) "
                f"| {rate:.1f} artists/s | ETA {eta_min:.0f} min",
                flush=True,
            )

    append_rows(OUTPUT, buffer)
    print("stopped; re-run to resume." if _stop_requested else "done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
