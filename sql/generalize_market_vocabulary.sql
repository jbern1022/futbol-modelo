-- One-off migration for the already-running database (fresh installs
-- get this via schema.sql). Extends predictions_market_check to also
-- allow MONEYLINE, SPREAD, TOTAL_POINTS -- the NFL/NBA market shapes,
-- per the multi-sport decision record. Schema prep only: nothing writes
-- these values yet (no grading path exists for SPREAD's signed-margin
-- semantics -- that's a separate, not-yet-done ticket). Postgres has no
-- ALTER CONSTRAINT for CHECK expressions, so this drops and recreates it;
-- purely additive to the allowed set, rejects nothing that exists today.
--
--     psql "$FUTBOL_DSN" -f sql/generalize_market_vocabulary.sql

ALTER TABLE futbol.predictions DROP CONSTRAINT IF EXISTS predictions_market_check;

ALTER TABLE futbol.predictions
    ADD CONSTRAINT predictions_market_check CHECK (market IN (
        '1X2', 'BTTS', 'TOTAL_GOALS', 'CORNERS', 'SOT',
        'PLAYER_GOALS', 'PLAYER_SAVES',
        'MONEYLINE', 'SPREAD', 'TOTAL_POINTS'));
