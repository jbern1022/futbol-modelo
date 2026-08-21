-- One-off data fix for the season-label mismatch (see Todoist,
-- src/ingestion/api_football.py's season_label_for()). Corrects the two
-- existing bad rows -- EPL and SERIE_A's current season, both created by
-- backfill_primary() with the old unconditional-bare-year bug -- to match
-- the hyphenated convention every prior season for those leagues already
-- uses. Value-only UPDATE: season_id is unchanged, so the 380+380
-- existing matches referencing it via foreign key are untouched and
-- don't need any migration themselves.
--
-- Verified safe to run without a coordinated redeploy: nothing in
-- api/main.py or the frontend parses/matches against the season label's
-- exact string format, they just pass it through as opaque text.
--
--     psql "$FUTBOL_DSN" -f sql/fix_season_label_mismatch.sql

UPDATE futbol.seasons
SET label = '2026-27'
WHERE label = '2026'
  AND league_id = (SELECT league_id FROM futbol.leagues WHERE code = 'EPL');

UPDATE futbol.seasons
SET label = '2026-27'
WHERE label = '2026'
  AND league_id = (SELECT league_id FROM futbol.leagues WHERE code = 'SERIE_A');
