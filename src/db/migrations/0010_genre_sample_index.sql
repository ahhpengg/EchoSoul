-- 0010_genre_sample_index.sql
-- Genre-filtered variant of the recommender's sampling index. The unfiltered
-- hot path scans idx_music_sample_vet (0004); with a genre filter that index
-- would fetch table rows across the whole emotion range hunting for matching
-- genres (a 100k-row-fetch scan for a thin bucket — the same failure mode the
-- header search hit, see 0007). Leading with canonical_genre gives each
-- selected bucket its own native sample_key-ordered range scan: the recommender
-- runs one windowed query per bucket (equality prefix -> ORDER BY sample_key is
-- served by the index, no filesort) and merges the windows in Python.
-- See docs/RECOMMENDATION.md "Genre filtering".

CREATE INDEX idx_music_genre_sample_vet
    ON music (canonical_genre, sample_key, valence, energy, tempo);
