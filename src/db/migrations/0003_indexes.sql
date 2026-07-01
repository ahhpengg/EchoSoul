-- 0003_indexes.sql
-- Indexes on the music catalogue. Applied here so a fresh setup is fully
-- indexed. For the one-off 1.2M-row bulk load, scripts/seed_database.py
-- (Track B) drops these first and recreates them after loading, because
-- maintaining indexes during a bulk insert is much slower (docs/DATABASE.md).

CREATE INDEX idx_music_vet ON music (valence, energy, tempo);
CREATE INDEX idx_music_genre ON music (genre);
CREATE INDEX idx_music_popularity ON music (popularity);
