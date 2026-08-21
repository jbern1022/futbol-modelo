-- One-off migration for the already-running database (fresh installs
-- get this via schema.sql). Additive: NOT NULL with a DEFAULT backfills
-- all 5 existing rows to 'soccer' automatically, nothing existing breaks.
--
-- Prerequisite for NFL (and later NBA): lets the framework distinguish
-- sports without a schema refactor when the second sport lands -- just
-- an ingestion adapter and a model, per the multi-sport decision record.
--
--     psql "$FUTBOL_DSN" -f sql/add_sport_to_leagues.sql

ALTER TABLE futbol.leagues
    ADD COLUMN IF NOT EXISTS sport TEXT NOT NULL DEFAULT 'soccer'
    CHECK (sport IN ('soccer', 'basketball', 'football'));
