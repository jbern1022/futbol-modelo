-- One-off migration for the already-running database (fresh installs
-- get this via schema.sql). Run AFTER sql/void_duplicate_match_predictions.sql
-- and the fbref-wc:nan cleanup -- this will fail with a unique-violation
-- if any duplicate external_ref values still exist.
--
-- Prevents the duplicate-match bug from recurring: a kickoff-time
-- correction between ingestion runs must find and update the existing
-- row (api_football.py's backfill_primary() now looks this up
-- explicitly before falling back to the natural key), not insert a
-- second row that predictions then get split across.
--
--     psql "$FUTBOL_DSN" -f sql/add_external_ref_unique_index.sql

CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_external_ref
    ON futbol.matches (external_ref) WHERE external_ref IS NOT NULL;
