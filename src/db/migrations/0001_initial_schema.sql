-- 0001_initial_schema.sql
-- Initial schema: music catalogue, emotion rule table, playlists, in-scope view.
-- See docs/DATABASE.md for column rationale.

CREATE TABLE IF NOT EXISTS music (
    track_id      VARCHAR(22)  NOT NULL,
    track_name    VARCHAR(500) NOT NULL,
    artists       VARCHAR(500) NOT NULL,
    artist_ids    VARCHAR(500) DEFAULT NULL,
    album_name    VARCHAR(500) DEFAULT NULL,
    genre         VARCHAR(100) DEFAULT NULL,
    genre_source  ENUM('mh','jbc_sub','jbc','artist') DEFAULT NULL,
    valence       FLOAT        NOT NULL,
    energy        FLOAT        NOT NULL,
    tempo         FLOAT        NOT NULL,
    popularity    TINYINT UNSIGNED DEFAULT NULL,
    duration_ms   INT UNSIGNED DEFAULT NULL,
    release_year  SMALLINT UNSIGNED DEFAULT NULL,
    created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (track_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS emotion_music_mapping (
    emotion       VARCHAR(20) NOT NULL,
    valence_min   FLOAT       NOT NULL,
    valence_max   FLOAT       NOT NULL,
    energy_min    FLOAT       NOT NULL,
    energy_max    FLOAT       NOT NULL,
    tempo_min     FLOAT       NOT NULL,
    tempo_max     FLOAT       NOT NULL,
    description   VARCHAR(255) DEFAULT NULL,
    PRIMARY KEY (emotion)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS playlist (
    playlist_id    INT          NOT NULL AUTO_INCREMENT,
    name           VARCHAR(200) NOT NULL,
    source_emotion VARCHAR(20)  DEFAULT NULL,
    created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (playlist_id),
    INDEX idx_playlist_emotion (source_emotion),
    INDEX idx_playlist_updated (updated_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS playlist_song (
    playlist_id    INT          NOT NULL,
    track_id       VARCHAR(22)  NOT NULL,
    position       INT UNSIGNED NOT NULL,
    added_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (playlist_id, track_id),
    INDEX idx_ps_position (playlist_id, position),
    FOREIGN KEY (playlist_id) REFERENCES playlist (playlist_id) ON DELETE CASCADE,
    FOREIGN KEY (track_id)    REFERENCES music    (track_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE OR REPLACE VIEW v_in_scope_music AS
SELECT track_id, track_name, artists, album_name, genre,
       valence, energy, tempo, popularity, duration_ms
FROM music
WHERE valence IS NOT NULL
  AND energy  IS NOT NULL
  AND tempo   IS NOT NULL
  AND tempo BETWEEN 20 AND 250;
