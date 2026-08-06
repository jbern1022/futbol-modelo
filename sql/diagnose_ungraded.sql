-- =============================================================
-- Why are predictions on finished matches still ungraded?
-- Read-only — safe against production.
--
--   psql "$FUTBOL_DSN" -P pager=off -f sql/diagnose_ungraded.sql
--
-- auto_grade.py reports these as "skipped (no stats yet)" and retries them
-- every night, forever. That single message covers several very different
-- situations, and they need different fixes:
--
--   a) the stats row for that team was never written at all
--   b) the row exists but the specific column is NULL
--   c) the prediction has no subject_team_id, so nothing can be looked up
--   d) the subject team is not actually in that match (a data bug)
--
-- (a) and (b) usually mean the source never supplied the stat, in which case
-- the prediction can never be graded and will sit in the ledger forever —
-- counted as a prediction made, but absent from every hit-rate figure. That
-- is a quiet honesty gap: the track record ends up computed over a subset,
-- selected by which stats happened to arrive.
-- =============================================================

\echo '=== 1. Ungraded predictions on finished matches, by market ==='
SELECT l.code AS league, p.market, COUNT(*) AS ungraded,
       MIN(m.kickoff_utc)::date AS oldest,
       MAX(m.kickoff_utc)::date AS newest
FROM futbol.predictions p
JOIN futbol.matches m USING (match_id)
JOIN futbol.seasons s USING (season_id)
JOIN futbol.leagues l USING (league_id)
LEFT JOIN futbol.prediction_grades g USING (prediction_id)
WHERE g.prediction_id IS NULL AND m.status = 'final'
GROUP BY 1, 2
ORDER BY 1, 2;


\echo ''
\echo '=== 2. Root cause for the team-stat markets (CORNERS, SOT) ==='
SELECT CASE
         WHEN p.subject_team_id IS NULL              THEN 'c) prediction has no subject_team_id'
         WHEN tms.match_id IS NULL                   THEN 'a) no team_match_stats row for that team'
         WHEN p.market = 'CORNERS'
              AND tms.corners IS NULL                THEN 'b) row exists, corners is NULL'
         WHEN p.market = 'SOT'
              AND tms.shots_on_target IS NULL        THEN 'b) row exists, shots_on_target is NULL'
         ELSE 'gradeable — investigate why auto_grade skipped it'
       END AS cause,
       COUNT(*) AS n
FROM futbol.predictions p
JOIN futbol.matches m USING (match_id)
LEFT JOIN futbol.prediction_grades g USING (prediction_id)
LEFT JOIN futbol.team_match_stats tms
       ON tms.match_id = p.match_id AND tms.team_id = p.subject_team_id
WHERE g.prediction_id IS NULL AND m.status = 'final'
  AND p.market IN ('CORNERS', 'SOT')
GROUP BY 1 ORDER BY n DESC;


\echo ''
\echo '=== 2b. Root cause for the player markets (PLAYER_GOALS, PLAYER_SAVES) ==='
-- The likely story here is different from the team markets. The team
-- definitely played; a named player may simply not have featured.
-- load_fixture_players skips anyone with zero or null minutes, so an unused
-- substitute gets no player_match_stats row at all and the prediction can
-- never be graded. Conventionally an anytime-scorer market voids when the
-- player does not appear — it does not lose — so hanging forever is the wrong
-- outcome as well as an invisible one.
SELECT CASE
         WHEN p.subject_player_id IS NULL           THEN 'c) prediction has no subject_player_id'
         WHEN pms.match_id IS NULL                  THEN 'a) player has no row — did not feature'
         WHEN p.market = 'PLAYER_GOALS'
              AND pms.goals IS NULL                 THEN 'b) row exists, goals is NULL'
         WHEN p.market = 'PLAYER_SAVES'
              AND pms.saves IS NULL                 THEN 'b) row exists, saves is NULL (not a keeper?)'
         ELSE 'gradeable — investigate why auto_grade skipped it'
       END AS cause,
       p.market,
       COUNT(*) AS n
FROM futbol.predictions p
JOIN futbol.matches m USING (match_id)
LEFT JOIN futbol.prediction_grades g USING (prediction_id)
LEFT JOIN futbol.player_match_stats pms
       ON pms.match_id = p.match_id AND pms.player_id = p.subject_player_id
WHERE g.prediction_id IS NULL AND m.status = 'final'
  AND p.market IN ('PLAYER_GOALS', 'PLAYER_SAVES')
GROUP BY 1, 2 ORDER BY n DESC;


\echo ''
\echo '=== 3. Sanity: is the subject team even in the match? ==='
-- Should return zero rows. Anything here is a real data bug: a prediction
-- about a team that did not play in the match it is attached to.
SELECT p.prediction_id, p.market, p.statement, p.subject_team_id,
       m.home_team_id, m.away_team_id
FROM futbol.predictions p
JOIN futbol.matches m USING (match_id)
WHERE p.subject_team_id IS NOT NULL
  AND p.subject_team_id NOT IN (m.home_team_id, m.away_team_id)
LIMIT 20;


\echo ''
\echo '=== 4. How complete are stats on finished matches overall? ==='
SELECT l.code AS league,
       COUNT(*)                                   AS final_team_rows,
       COUNT(tms.corners)                         AS with_corners,
       COUNT(tms.shots_on_target)                 AS with_sot,
       ROUND(100.0 * COUNT(tms.corners)
             / NULLIF(COUNT(*), 0), 1)            AS pct_corners
FROM futbol.matches m
JOIN futbol.seasons s USING (season_id)
JOIN futbol.leagues l USING (league_id)
LEFT JOIN futbol.team_match_stats tms ON tms.match_id = m.match_id
WHERE m.status = 'final'
GROUP BY 1 ORDER BY 1;


\echo ''
\echo '=== 5. How long have they been waiting? ==='
-- Anything months old is not "not yet" — the stat is never arriving, and the
-- prediction is permanently invisible to the track record.
SELECT CASE
         WHEN now() - m.kickoff_utc < interval '2 days'  THEN 'under 2 days'
         WHEN now() - m.kickoff_utc < interval '7 days'  THEN '2-7 days'
         WHEN now() - m.kickoff_utc < interval '30 days' THEN '7-30 days'
         ELSE 'over 30 days'
       END AS waiting,
       COUNT(*) AS n
FROM futbol.predictions p
JOIN futbol.matches m USING (match_id)
LEFT JOIN futbol.prediction_grades g USING (prediction_id)
WHERE g.prediction_id IS NULL AND m.status = 'final'
GROUP BY 1
ORDER BY MIN(now() - m.kickoff_utc);
