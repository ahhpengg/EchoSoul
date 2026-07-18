-- 0009_canonical_genre.sql
-- Normalised genre bucket for the user-facing genre filter. The raw `genre`
-- column is a 3,994-value Last.fm/dataset folksonomy (synonyms, spelling
-- variants, nationality/instrument/junk tags); `canonical_genre` collapses it
-- into the 23-bucket owner-reviewed vocabulary defined by
-- data/seed/genre_canonical_map.csv. The column is derived data, populated by
-- scripts/apply_genre_mapping.py (bulk data load is not a migration); NULL
-- means the raw tag was junk/unmapped or the row has no genre at all
-- (external tracks included), so filtered queries simply never match it.
-- See docs/DATABASE.md "Canonical genre".

ALTER TABLE music
    ADD COLUMN canonical_genre VARCHAR(50) DEFAULT NULL AFTER genre_source;

-- Display/count queries only. The genre-filtered recommendation hot path gets
-- its own index shape when the recommender change lands, not here.
CREATE INDEX idx_music_canonical_genre ON music (canonical_genre);

CREATE OR REPLACE VIEW v_in_scope_music AS
SELECT track_id, track_name, artists, album_name, genre, canonical_genre,
       valence, energy, tempo, popularity, duration_ms, sample_key
FROM music
WHERE valence IS NOT NULL
  AND energy  IS NOT NULL
  AND tempo   IS NOT NULL
  AND tempo BETWEEN 20 AND 250;
