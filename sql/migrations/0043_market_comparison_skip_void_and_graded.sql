-- Fix v_market_comparison (migration 0011) showing voided and already-
-- graded predictions in the Track Record "Model vs. the market" section.
--
-- Found 2026-10-13 investigating a Hull City row (87.1% model vs 23.3%
-- market on a match that had already finished 0-0):
--
--  1. The dedup picked the EARLIEST prediction per match/side without
--     excluding voided ones. Since ADR-012 (3-day slate window), stale
--     slates are voided and regenerated, so the earliest row is often
--     the voided one. 168 of 170 scheduled rows and 132 of 351 final
--     rows showed a voided probability (e.g. Coventry v Newcastle at
--     88.8% from a voided v1 row, when the live v4 prediction was
--     60.4%). Fixtures outside the 3-day window only have voided rows,
--     so they now drop out until a fresh slate exists.
--  2. No status filter, though the section is described as fixtures that
--     haven't been graded yet. 351 of 524 rows were final, 3 abandoned.
--     Only status = 'scheduled' remains. Graded matches are already
--     covered by v_graded_predictions / v_closing_line_value.
--
-- Dedup now mirrors v_graded_predictions: skip void-graded predictions,
-- earliest remaining prediction_id wins. Column list is unchanged, so
-- CREATE OR REPLACE keeps the futbol_ro grant from migration 0012.
CREATE OR REPLACE VIEW v_market_comparison AS
SELECT
    l.code            AS league,
    m.match_id,
    th.name           AS home_team,
    ta.name           AS away_team,
    m.kickoff_utc,
    m.status,
    p.side,
    p.probability                                 AS model_probability,
    ROUND(AVG(mo.no_vig_probability)::numeric, 4)  AS market_probability,
    COUNT(DISTINCT mo.bookmaker_id)                AS n_bookmakers
FROM (
    SELECT p.*, ROW_NUMBER() OVER (
        PARTITION BY p.match_id, p.market, p.side, p.line,
                     p.subject_team_id, p.subject_player_id
        ORDER BY p.prediction_id
    ) AS rn
    FROM predictions p
    LEFT JOIN prediction_grades g ON g.prediction_id = p.prediction_id
    WHERE p.market = '1X2'
      AND (g.outcome IS NULL OR g.outcome <> 'void')
) p
JOIN matches m ON m.match_id = p.match_id
JOIN teams th ON th.team_id = m.home_team_id
JOIN teams ta ON ta.team_id = m.away_team_id
JOIN seasons s ON s.season_id = m.season_id
JOIN leagues l ON l.league_id = s.league_id
JOIN match_odds mo ON mo.match_id = m.match_id AND LOWER(mo.selection) = p.side
WHERE p.rn = 1
  AND m.status = 'scheduled'
GROUP BY l.code, m.match_id, th.name, ta.name, m.kickoff_utc, m.status, p.side, p.probability;
