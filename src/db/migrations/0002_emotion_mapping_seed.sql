-- 0002_emotion_mapping_seed.sql
-- Seed the 5-row recommendation rule table. Values from CP1 planning doc
-- section 3.10, Table 13. Canonical copy lives in
-- data/seed/emotion_music_mapping.sql; keep both in sync.
-- ON DUPLICATE KEY UPDATE makes a re-run safe and lets a later migration tweak
-- a bound by re-applying with new values.

INSERT INTO emotion_music_mapping
    (emotion, valence_min, valence_max, energy_min, energy_max, tempo_min, tempo_max, description)
VALUES
    ('happy',     0.66, 1.00, 0.66, 1.00, 120.0, 250.0, 'High valence, high energy, fast tempo - upbeat positive music'),
    ('surprised', 0.66, 1.00, 0.66, 1.00, 120.0, 250.0, 'Same target as happy - both are positive high-arousal emotions'),
    ('sad',       0.00, 0.34, 0.00, 0.34,  20.0,  90.0, 'Low valence, low energy, slow tempo - melancholic music'),
    ('angry',     0.00, 0.34, 0.66, 1.00, 120.0, 250.0, 'Low valence, high energy, fast tempo - intense aggressive music'),
    ('neutral',   0.34, 0.66, 0.34, 0.66,  90.0, 120.0, 'Moderate on all dimensions - balanced ambient music')
ON DUPLICATE KEY UPDATE
    valence_min = VALUES(valence_min),
    valence_max = VALUES(valence_max),
    energy_min  = VALUES(energy_min),
    energy_max  = VALUES(energy_max),
    tempo_min   = VALUES(tempo_min),
    tempo_max   = VALUES(tempo_max),
    description = VALUES(description);
