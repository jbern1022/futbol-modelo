-- The 9 orphaned duplicate matches from the kickoff-drift bug (see
-- sql/void_duplicate_match_predictions.sql) were left at status =
-- 'scheduled' with real future kickoff times after their predictions
-- were voided. They don't currently show up in the live fixture list
-- purely by coincidence of date -- as time moves forward they will
-- start appearing as legitimate-looking upcoming fixtures carrying
-- stale, voided predictions, since /fixtures and auto_slate.py both
-- filter on status = 'scheduled'.
--
-- Reuses the existing 'canc' status (already used for 9 unrelated
-- real postponed/canceled matches from 2023-2024) rather than
-- inventing a new status value -- every query in the codebase that
-- filters on status = 'scheduled' or status = 'final' already
-- excludes 'canc' rows naturally, so this needs no other code change.
--
--     psql "$FUTBOL_DSN" -f sql/cancel_superseded_duplicate_matches.sql

UPDATE futbol.matches
SET status = 'canc'
WHERE match_id IN (4420, 4434, 4441, 4469, 4482, 4483, 4485, 4573, 4682)
  AND external_ref LIKE '%-superseded-by-%';
