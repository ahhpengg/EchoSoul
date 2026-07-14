-- 0006_fulltext_search.sql
-- FULLTEXT index backing the header search bar (docs/DATABASE.md "Track
-- search index"). Covers title + artists so typing either finds the song.
-- Building the first FULLTEXT index on InnoDB also adds the hidden FTS_DOC_ID
-- column (full table rebuild) -- expect a few minutes on the 1.3M-row catalogue.

ALTER TABLE music ADD FULLTEXT INDEX ft_music_search (track_name, artists);
