-- data/seed/emotion_music_mapping.sql
-- Canonical seed for the 5-row recommendation rule table (CP1 planning doc
-- section 3.10, Table 13). Applied by migration 0002_emotion_mapping_seed.sql;
-- this committed copy is the source of truth and can also be loaded standalone.

INSERT INTO emotion_music_mapping
    (emotion, valence_min, valence_max, energy_min, energy_max, tempo_min, tempo_max, description)
VALUES
    ('happy',     0.66, 1.00, 0.66, 1.00, 120.0, 250.0, 'High valence, high energy, fast tempo - upbeat positive music'),
    ('surprised', 0.66, 1.00, 0.66, 1.00, 120.0, 250.0, 'Same target as happy - both are positive high-arousal emotions'),
    ('sad',       0.00, 0.34, 0.00, 0.34,  20.0,  90.0, 'Low valence, low energy, slow tempo - melancholic music'),
    ('angry',     0.00, 0.34, 0.66, 1.00, 120.0, 250.0, 'Low valence, high energy, fast tempo - intense aggressive music'),
    ('neutral',   0.34, 0.66, 0.34, 0.66,  90.0, 120.0, 'Moderate on all dimensions - balanced ambient music');
