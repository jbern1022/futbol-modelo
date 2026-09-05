-- Reconciles real schema drift found while investigating the "Adopt a
-- migrations tool" ticket: two near-identical unique indexes exist on
-- the live predictions table that were never in git at all --
-- predictions_natural_key (what persist_slate's ON CONFLICT actually
-- targets; confirmed via pg_stat_user_indexes at ~5.9M scans) and
-- predictions_natural_key_idx (confirmed 0 scans ever -- an orphaned
-- earlier attempt, safe to drop).
--
-- This migration is a no-op on the live database (the real index
-- already exists) -- it exists so schema.sql and a fresh database
-- match live reality, and so the dead duplicate index is removed.

CREATE UNIQUE INDEX IF NOT EXISTS predictions_natural_key
    ON predictions (
        match_id, model_version_id, market,
        COALESCE(subject_team_id, '-1'::integer),
        COALESCE(subject_player_id, '-1'::integer),
        COALESCE(side, ''::text),
        COALESCE(line, '-9999'::integer::numeric)
    );

DROP INDEX IF EXISTS predictions_natural_key_idx;
