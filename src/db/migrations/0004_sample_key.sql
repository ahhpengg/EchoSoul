-- 0004_sample_key.sql
-- Add a random sampling key so the recommender can pull a random, representative
-- slice of an emotion's candidate pool instead of the biased low-valence slice
-- an unordered LIMIT returns. Derived deterministically from track_id via MD5:
-- uniform in [0, 1), uncorrelated with audio features, and binlog-safe (RAND()
-- is rejected as replica-unsafe in DDL/DML). As a generated column it is
-- computed for existing and future rows automatically and cannot be inserted
-- into, so the seed script needs no change. See docs/RECOMMENDATION.md Step 3.

ALTER TABLE music
    ADD COLUMN sample_key DOUBLE
        AS (CONV(SUBSTRING(MD5(track_id), 1, 8), 16, 10) / 4294967295) STORED;

-- Composite so the recommender's candidate query is served entirely from the
-- index: it scans in sample_key order from a random start (satisfying ORDER BY
-- sample_key with no filesort) and filters valence/energy/tempo in-index (index
-- condition pushdown), touching table rows only for the ~1000 it keeps. The
-- filter columns MUST follow sample_key here; leading with them instead would
-- force a filesort on sample_key. The query uses FORCE INDEX on this index
-- because the optimizer otherwise misreads the wide sample_key range as a full
-- scan. See docs/RECOMMENDATION.md Step 3.
CREATE INDEX idx_music_sample_vet ON music (sample_key, valence, energy, tempo);

CREATE OR REPLACE VIEW v_in_scope_music AS
SELECT track_id, track_name, artists, album_name, genre,
       valence, energy, tempo, popularity, duration_ms, sample_key
FROM music
WHERE valence IS NOT NULL
  AND energy  IS NOT NULL
  AND tempo   IS NOT NULL
  AND tempo BETWEEN 20 AND 250;
