-- =============================================================
-- Migration 001 — make predictions_natural_key actually enforce uniqueness.
--
--   psql "$FUTBOL_DSN" -f sql/migrations/001_predictions_natural_key_nulls.sql
--
-- PROBLEM
-- predictions_natural_key was declared as:
--   UNIQUE (match_id, model_version_id, market, subject_team_id,
--           subject_player_id, side, line)
-- Postgres UNIQUE defaults to NULLS DISTINCT: a row with a NULL in any key
-- column never conflicts with anything. Every prediction shape has at least
-- one NULL there —
--   1X2            subject_player_id, line
--   BTTS           subject_team_id, subject_player_id, line
--   TOTAL_GOALS    subject_team_id, subject_player_id
--   CORNERS / SOT  subject_player_id
--   PLAYER_*       subject_team_id
-- so persist_slate()'s ON CONFLICT DO NOTHING has never suppressed a single
-- duplicate. Same defect as the teams.name constraint fixed in
-- sql/fix_duplicate_teams.sql.
--
-- FIX
-- A unique index over COALESCE'd columns, which works on every supported
-- Postgres release. (PG15+ could use UNIQUE NULLS NOT DISTINCT instead; this
-- form was chosen so the migration does not depend on the server version.)
-- Sentinels are safe: team_id and player_id are SERIAL and therefore always
-- positive, and no market uses a negative line.
--
-- SCOPE — READ THIS
-- This makes the constraint functional. It does NOT by itself make slate
-- generation idempotent across days, because model_versions.version_tag
-- currently embeds the run date (f"{home}_v_{away}_{date}"), so a re-run on a
-- different day mints a new model_version_id and produces a legitimately
-- different key. Fixing the model registry is a separate change.
-- =============================================================

BEGIN;

SET search_path TO futbol;

-- Refuse to proceed if duplicates already exist. They cannot simply be
-- deleted: predictions carries a BEFORE DELETE trigger that raises
-- unconditionally, and working around it would break the ledger guarantee the
-- project is built on. If this fires, decide deliberately how to reconcile
-- the history before re-running — do not disable the trigger casually.
DO $$
DECLARE
    dup_groups INT;
BEGIN
    SELECT COUNT(*) INTO dup_groups FROM (
        SELECT 1
        FROM predictions
        GROUP BY match_id, model_version_id, market,
                 COALESCE(subject_team_id, -1),
                 COALESCE(subject_player_id, -1),
                 COALESCE(side, ''),
                 COALESCE(line, -9999)
        HAVING COUNT(*) > 1
    ) d;

    IF dup_groups > 0 THEN
        RAISE EXCEPTION
            'Cannot apply: % duplicate prediction group(s) already exist. '
            'The unique index would fail. Inspect them first with the query in '
            'the comment below, then decide how to reconcile before re-running.',
            dup_groups;
    END IF;
END $$;

--  SELECT match_id, model_version_id, market, subject_team_id,
--         subject_player_id, side, line, COUNT(*) AS n
--  FROM futbol.predictions
--  GROUP BY 1,2,3,4,5,6,7 HAVING COUNT(*) > 1 ORDER BY n DESC;

ALTER TABLE predictions DROP CONSTRAINT IF EXISTS predictions_natural_key;

CREATE UNIQUE INDEX predictions_natural_key ON predictions (
    match_id,
    model_version_id,
    market,
    COALESCE(subject_team_id, -1),
    COALESCE(subject_player_id, -1),
    COALESCE(side, ''),
    COALESCE(line, -9999)
);

COMMIT;
