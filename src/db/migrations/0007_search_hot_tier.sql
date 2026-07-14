-- 0007_search_hot_tier.sql
-- Hot search tier for the header search bar (docs/DATABASE.md "Track search").
--
-- Searching `music` with ORDER BY popularity forces a row fetch for EVERY
-- FULLTEXT match (34k+ docs for a broad prefix like "love*") on a table far
-- bigger than the default InnoDB buffer pool: 3-9 s per query, measured. Only
-- ~116k of the 1.31M catalogue rows carry a popularity value at all, so the
-- popularity-ordered results can only ever come from that slice. This table is
-- that slice, denormalised (all display columns) with its own FULLTEXT index:
-- small enough that even the broadest prefix search answers in tens of ms.
-- Tracks WITHOUT popularity are reachable via the relevance-ordered fallback
-- on `music` (migration 0006), which uses InnoDB's fast rank-sort path.
--
-- Derived data: rebuild this table (delete + re-run these statements) if the
-- music catalogue is ever re-seeded.

CREATE TABLE IF NOT EXISTS music_search_hot (
    track_id      VARCHAR(22)      NOT NULL,
    track_name    VARCHAR(500)     NOT NULL,
    artists       VARCHAR(500)     NOT NULL,
    album_name    VARCHAR(500)     DEFAULT NULL,
    duration_ms   INT UNSIGNED     DEFAULT NULL,
    popularity    TINYINT UNSIGNED NOT NULL,
    PRIMARY KEY (track_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO music_search_hot (track_id, track_name, artists, album_name, duration_ms, popularity)
SELECT track_id, track_name, artists, album_name, duration_ms, popularity
FROM music
WHERE popularity IS NOT NULL;

ALTER TABLE music_search_hot ADD FULLTEXT INDEX ft_hot_search (track_name, artists);
