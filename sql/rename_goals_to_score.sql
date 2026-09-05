-- NOT APPLIED to the live DB as of 2026-08-21 -- deliberately held back.
--
-- This renames a column every currently-deployed service depends on
-- (futbol-api and futbol-web are running Docker images built from code
-- that still says home_goals/away_goals). Applying this against the live
-- DB before those images are rebuilt and redeployed breaks every
-- /fixtures, /fixtures/{id}/slate, and /scorecard call on the live site
-- immediately -- there is no backwards-compatible window.
--
-- Run this ONLY as part of a coordinated deploy:
--   1. Rebuild futbol-api and futbol-web images from the current repo
--      (this rename is already in the code: api/main.py, grader.py,
--      generate_slate.py, auto_grade.py, the ingestion loaders, and both
--      frontend files all already use home_score/away_score).
--   2. Run this migration against FUTBOL_DSN.
--   3. Redeploy both images (kubectl delete pod to force the fresh pull)
--      immediately after -- steps 2 and 3 should happen back-to-back,
--      not with a gap.
--
--     psql "$FUTBOL_DSN" -f sql/rename_goals_to_score.sql

ALTER TABLE futbol.matches RENAME COLUMN home_goals TO home_score;
ALTER TABLE futbol.matches RENAME COLUMN away_goals TO away_score;
ALTER TABLE futbol.matches RENAME COLUMN went_to_et TO went_to_ot;
-- went_to_pens deliberately NOT renamed -- penalty shootouts are a
-- soccer/knockout-tournament concept that doesn't map onto NFL/NBA at
-- all (neither sport has one), so there's nothing to generalize it to.
-- It stays soccer-specific and simply goes unused for other sports.
