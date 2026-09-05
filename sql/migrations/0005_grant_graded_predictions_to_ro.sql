-- futbol_ro's grants come from `ALTER DEFAULT PRIVILEGES FOR ROLE postgres
-- IN SCHEMA futbol GRANT SELECT ON TABLES TO futbol_ro` (found while
-- inspecting a real pg_dump during the backup restore drill) -- objects
-- created by any OTHER role, including the app's own `futbol` role (as
-- migrations run via scripts/migrate.py do), aren't covered by that
-- rule. v_graded_predictions (migration 0003) was queried only
-- indirectly through v_calibration/v_season_scorecard until GET
-- /predictions started querying it directly -- direct access needs
-- its own explicit grant.
GRANT SELECT ON futbol.v_graded_predictions TO futbol_ro;
