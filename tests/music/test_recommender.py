"""Tests for the rule-based recommender.

Integration tests against the real ``echosoul`` catalogue (docs/RECOMMENDATION.md
defaults to this). Skipped if MySQL is unreachable. All tests are read-only.
"""

from __future__ import annotations

import pytest

from src.db import connection
from src.music import recommender

RESULT_KEYS = {
    "track_id",
    "track_name",
    "artists",
    "album_name",
    "genre",
    "valence",
    "energy",
    "tempo",
    "duration_ms",
}


def _db_available() -> bool:
    try:
        with connection.get_connection() as conn:
            conn.ping(reconnect=False, attempts=1)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="MySQL not reachable / .env not configured"
)


def test_unsupported_emotion_raises():
    with pytest.raises(ValueError):
        recommender.generate_playlist("ennui")


@pytest.mark.parametrize("emotion", sorted(recommender.SUPPORTED_EMOTIONS))
def test_each_emotion_returns_full_playlist(emotion):
    playlist = recommender.generate_playlist(emotion, size=25, seed=1)
    # Every seeded emotion has tens of thousands of candidates, so the pool is
    # never the limiting factor at the default size.
    assert len(playlist) == 25


def test_default_size_is_20():
    assert len(recommender.generate_playlist("happy", seed=1)) == 20


def test_result_dicts_have_documented_keys():
    track = recommender.generate_playlist("happy", size=1, seed=1)[0]
    assert set(track) == RESULT_KEYS


def test_same_seed_is_deterministic():
    p1 = recommender.generate_playlist("happy", size=10, seed=42)
    p2 = recommender.generate_playlist("happy", size=10, seed=42)
    assert [t["track_id"] for t in p1] == [t["track_id"] for t in p2]


def test_different_seeds_differ():
    p1 = recommender.generate_playlist("happy", size=10, seed=42)
    p2 = recommender.generate_playlist("happy", size=10, seed=43)
    # Full equality across two seeds is astronomically unlikely.
    assert [t["track_id"] for t in p1] != [t["track_id"] for t in p2]


def test_size_caps_at_candidate_pool_limit():
    # Requesting more than the pool cap returns exactly the capped pool size.
    playlist = recommender.generate_playlist("happy", size=5000, seed=1)
    assert len(playlist) == recommender.CANDIDATE_POOL_LIMIT


def test_sampling_reaches_high_valence_not_just_the_floor():
    # Regression guard for the old unordered-LIMIT bias: it only ever returned
    # the ~1000 lowest-valence "happy" tracks (valence ~0.66). With random
    # sample_key windowing the whole 0.66-1.00 range must be reachable.
    seen_max = max(
        track["valence"]
        for seed in range(20)
        for track in recommender.generate_playlist("happy", size=25, seed=seed)
    )
    assert seen_max > 0.90


@pytest.mark.parametrize("emotion", sorted(recommender.SUPPORTED_EMOTIONS))
def test_returned_tracks_satisfy_the_rule(emotion):
    rule = connection.fetchone(
        "SELECT valence_min, valence_max, energy_min, energy_max, "
        "       tempo_min, tempo_max "
        "FROM emotion_music_mapping WHERE emotion = %s",
        (emotion,),
    )
    for track in recommender.generate_playlist(emotion, size=25, seed=7):
        assert rule["valence_min"] <= track["valence"] <= rule["valence_max"]
        assert rule["energy_min"] <= track["energy"] <= rule["energy_max"]
        assert rule["tempo_min"] <= track["tempo"] <= rule["tempo_max"]


def test_count_candidates_is_positive():
    assert recommender.count_candidates("happy") > recommender.CANDIDATE_POOL_LIMIT


def test_count_candidates_unsupported_raises():
    with pytest.raises(ValueError):
        recommender.count_candidates("ennui")


# --- genre filtering (docs/RECOMMENDATION.md "Genre filtering") ---------------


def _canonical_genres_of(playlist: list[dict]) -> set[str]:
    ids = [t["track_id"] for t in playlist]
    marks = ", ".join(["%s"] * len(ids))
    rows = connection.fetchall(
        f"SELECT DISTINCT canonical_genre AS b FROM music WHERE track_id IN ({marks})",
        tuple(ids),
    )
    return {r["b"] for r in rows}


def test_genre_filter_only_returns_picked_buckets():
    playlist = recommender.generate_playlist("happy", seed=3, genres=["Pop", "K-Pop"])
    assert len(playlist) == 20
    assert _canonical_genres_of(playlist) <= {"Pop", "K-Pop"}


def test_genre_filter_is_deterministic_regardless_of_picker_order():
    p1 = recommender.generate_playlist("happy", seed=7, genres=["Pop", "K-Pop"])
    p2 = recommender.generate_playlist("happy", seed=7, genres=["K-Pop", "Pop", "K-Pop"])
    assert [t["track_id"] for t in p1] == [t["track_id"] for t in p2]


def test_thin_bucket_yields_short_but_pure_playlist():
    # K-Pop x sad is the catalogue's one thin combo (docs/RECOMMENDATION.md);
    # policy is a shorter playlist, never a top-up from other genres.
    playlist = recommender.generate_playlist("sad", seed=1, genres=["K-Pop"])
    assert 0 < len(playlist) < recommender.DEFAULT_PLAYLIST_SIZE
    assert _canonical_genres_of(playlist) == {"K-Pop"}


def test_unknown_bucket_matches_nothing():
    assert recommender.generate_playlist("happy", seed=1, genres=["Polka Fusion"]) == []


def test_genre_filtered_tracks_still_satisfy_the_rule():
    rule = connection.fetchone(
        "SELECT valence_min, valence_max, energy_min, energy_max, "
        "       tempo_min, tempo_max "
        "FROM emotion_music_mapping WHERE emotion = %s",
        ("angry",),
    )
    for track in recommender.generate_playlist("angry", size=25, seed=7, genres=["Metal"]):
        assert rule["valence_min"] <= track["valence"] <= rule["valence_max"]
        assert rule["energy_min"] <= track["energy"] <= rule["energy_max"]
        assert rule["tempo_min"] <= track["tempo"] <= rule["tempo_max"]


def test_list_genre_buckets_matches_seed_vocabulary():
    buckets = recommender.list_genre_buckets()
    assert len(buckets) == 23
    assert buckets == sorted(buckets)
    assert {"Pop", "SEA Pop", "C-Pop / Mandopop", "K-Pop"} <= set(buckets)
