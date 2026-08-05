-- =============================================================
-- Migration 002 — make enforce_pre_kickoff() independent of the caller's
-- search_path.
--
--   psql "$FUTBOL_DSN" -f sql/migrations/002_enforce_pre_kickoff_search_path.sql
--
-- PROBLEM
-- The trigger function read from an unqualified `matches`. PL/pgSQL resolves
-- names at execution time against the CALLER's search_path, not the one in
-- effect when the function was created, so the `SET search_path TO futbol` at
-- the top of schema.sql did not carry into it. Any client connecting with the
-- default search_path ("$user", public) — which is every psycopg2 connection
-- in this project, since the application fully qualifies its own tables
-- instead of setting a search_path — hit:
--
--   ERROR: relation "matches" does not exist
--   CONTEXT: PL/pgSQL function futbol.enforce_pre_kickoff() line 4
--
-- ...on every insert into futbol.predictions.
--
-- If production has been writing predictions successfully, search_path is
-- being set somewhere outside this repo (commonly `ALTER ROLE futbol SET
-- search_path ...`). That is an undocumented environmental dependency: a
-- fresh deploy of schema.sql onto a clean server would fail immediately.
-- This migration removes the dependency either way.
--
-- Safe to run repeatedly. Does not touch data; the trigger keeps pointing at
-- the same function name.
-- =============================================================

BEGIN;

CREATE OR REPLACE FUNCTION futbol.enforce_pre_kickoff() RETURNS trigger AS $$
DECLARE ko TIMESTAMPTZ;
BEGIN
    SELECT kickoff_utc INTO ko FROM futbol.matches WHERE match_id = NEW.match_id;
    IF NEW.locked_at >= ko THEN
        RAISE EXCEPTION 'prediction locked after kickoff (% >= %)', NEW.locked_at, ko;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql
SET search_path = futbol, pg_temp;

COMMIT;
