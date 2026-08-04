-- =============================================================
-- Phase 1 verification queries. Read-only — safe to run against prod.
--   psql "$FUTBOL_DSN" -f sql/verify_phase1.sql
--
-- Two open questions from the 2026-08 code review. Both change the scope
-- of downstream work, and both are cheap to answer.
-- =============================================================

\echo '=== Q1a: xG coverage per league ==============================='
-- HYPOTHESIS: team_match_stats.xg is NULL for MLS, because
-- api_football.backfill_primary() never writes xg (not on the current tier).
-- Understat supplies xg for EPL/SERIE_A/LA_LIGA but does not cover MLS.
-- EXPECT: MLS pct_with_xg = 0.0
SELECT l.code                                                        AS league,
       COUNT(*)                                                      AS team_match_rows,
       COUNT(tms.xg)                                                 AS rows_with_xg,
       ROUND(100.0 * COUNT(tms.xg) / NULLIF(COUNT(*), 0), 1)         AS pct_with_xg
FROM futbol.team_match_stats tms
JOIN futbol.matches m  ON m.match_id  = tms.match_id
JOIN futbol.seasons s  ON s.season_id = m.season_id
JOIN futbol.leagues l  ON l.league_id = s.league_id
GROUP BY l.code
ORDER BY l.code;


\echo ''
\echo '=== Q1b: rows surviving the props-training dropna() ============'
-- generate_slate.fit_props_model() selects these features then calls
-- df.dropna(). If xg_for_r5 / xg_against_r5 are NULL for MLS, every MLS row
-- is dropped and the "MLS" corners model is trained purely on European data,
-- then asked to predict MLS fixtures with two features missing (LightGBM
-- tolerates NaN, so it fails silently rather than raising).
-- EXPECT IF HYPOTHESIS HOLDS: MLS rows_after_dropna = 0
SELECT l.code AS league,
       COUNT(*) AS rows_after_dropna
FROM futbol.team_match_features f
JOIN futbol.matches m ON m.match_id = f.match_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.team_match_stats tms
  ON tms.match_id = f.match_id AND tms.team_id = f.team_id
WHERE tms.corners           IS NOT NULL
  AND f.corners_for_r5      IS NOT NULL
  AND f.corners_against_r5  IS NOT NULL
  AND f.shots_for_r5        IS NOT NULL
  AND f.shots_against_r5    IS NOT NULL
  AND f.xg_for_r5           IS NOT NULL
  AND f.xg_against_r5       IS NOT NULL
  AND f.rest_days           IS NOT NULL
GROUP BY l.code
ORDER BY l.code;


\echo ''
\echo '=== Q1c: how stale are the feature tables? ====================='
-- sql/features.sql is not run by run_nightly.sh, so team_match_features can
-- lag matches by however long it has been since it was run by hand.
SELECT (SELECT MAX(kickoff_utc) FROM futbol.matches
         WHERE status = 'final')                      AS latest_final_match,
       (SELECT MAX(kickoff_utc) FROM futbol.team_match_features)
                                                      AS latest_feature_row,
       (SELECT MAX(kickoff_utc) FROM futbol.matches WHERE status = 'final')
         - (SELECT MAX(kickoff_utc) FROM futbol.team_match_features)
                                                      AS feature_lag;


\echo ''
\echo '=== Q2: does predictions have the ON CONFLICT constraint? ======'
-- predictions.persist_slate() issues:
--   ON CONFLICT (match_id, model_version_id, market, subject_team_id,
--                subject_player_id, side, line)
-- With no matching UNIQUE constraint or index, Postgres raises
-- "no unique or exclusion constraint matching the ON CONFLICT specification"
-- on every insert. If nothing below covers that exact column list, slate
-- generation is broken (or is being saved by a constraint added by hand and
-- never committed to schema.sql).
SELECT conname                      AS constraint_name,
       contype                      AS type,
       pg_get_constraintdef(oid)    AS definition
FROM pg_constraint
WHERE conrelid = 'futbol.predictions'::regclass
ORDER BY contype, conname;

\echo ''
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'futbol' AND tablename = 'predictions'
ORDER BY indexname;


\echo ''
\echo '=== Q3: sanity — has anything actually been written lately? ===='
SELECT MAX(created_at) AS latest_prediction_written,
       COUNT(*)        AS total_predictions
FROM futbol.predictions;

SELECT MAX(graded_at)  AS latest_grade_written,
       COUNT(*)        AS total_grades
FROM futbol.prediction_grades;
