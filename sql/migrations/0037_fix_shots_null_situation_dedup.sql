-- Root cause of Todoist "BUG: futbol.shots result='Goal' is badly
-- wrong for La Liga" (found 2026-09-30 while validating the in-play
-- win-probability experiment): shots_natural_key's UNIQUE CONSTRAINT
-- includes `situation`, a nullable column -- and Postgres (like
-- standard SQL) never treats two NULLs as equal in a UNIQUE
-- constraint, so ON CONFLICT silently failed to dedupe any shot with
-- situation IS NULL. Confirmed live: 6.7% of La Liga's shots have
-- NULL situation vs ~1% for EPL/SERIE_A -- La Liga wasn't uniquely
-- buggy, it just hit this far more often. Real damage confirmed: 1365
-- duplicate rows, 100% La Liga (a single minute-44 goal had landed
-- FIVE separate times under five different shot_ids).
--
-- Fix, in order: dedupe existing rows (keep the earliest shot_id per
-- true natural key, treating NULL situation as equal to itself via
-- COALESCE), then replace the constraint with an expression-based
-- unique index that actually enforces that equivalence going forward.
-- src/ingestion/loader.py's INSERT ... ON CONFLICT is updated to match
-- in the same commit as this migration.

DELETE FROM shots a
USING shots b
WHERE a.shot_id > b.shot_id
  AND a.match_id = b.match_id
  AND a.player_id = b.player_id
  AND a.minute = b.minute
  AND a.x = b.x
  AND a.y = b.y
  AND COALESCE(a.situation, '') = COALESCE(b.situation, '')
  AND a.result = b.result;

ALTER TABLE shots DROP CONSTRAINT IF EXISTS shots_natural_key;

CREATE UNIQUE INDEX IF NOT EXISTS shots_natural_key ON shots (
    match_id, player_id, minute, x, y, COALESCE(situation, ''), result
);
