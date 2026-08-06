-- One-off migration for the already-running database (fresh installs get
-- this via the CHECK constraint now in schema.sql's predictions table).
--
-- Verified 2026-08-06 against live data before writing this: SELECT
-- DISTINCT market FROM futbol.predictions returns exactly the 7 values
-- below, so this constraint rejects nothing that already exists -- it
-- only prevents a future typo from creating a phantom market that never
-- grades (the schema comment previously listed 'TEAM_CORNERS',
-- 'TEAM_SHOTS', 'PLAYER_SHOTS', 'PLAYER_GOAL', none of which the code
-- actually writes).
--
--     psql "$FUTBOL_DSN" -f sql/add_market_check_constraint.sql

ALTER TABLE futbol.predictions
    ADD CONSTRAINT predictions_market_check CHECK (market IN (
        '1X2', 'BTTS', 'TOTAL_GOALS', 'CORNERS', 'SOT',
        'PLAYER_GOALS', 'PLAYER_SAVES'));
