-- UI half of "real bookmaker odds comparison" -- the view backing the
-- new /v1/odds-comparison endpoint and the Track Record page's market
-- comparison section. Deliberately not gated on grading (unlike
-- v_calibration/v_season_scorecard): match_odds is fetched for
-- still-scheduled fixtures, so almost every row here is a pre-game
-- estimate compared against another pre-game estimate. Rows survive
-- past kickoff untouched (nothing deletes match_odds), so this view
-- naturally also covers already-graded matches once enough time passes.
--
-- Same natural-key dedup as v_graded_predictions (partition by the
-- prediction's natural key, ORDER BY prediction_id ASC so the first,
-- pre-kickoff-locked prediction wins over any later regeneration).
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
    WHERE p.market = '1X2'
) p
JOIN matches m ON m.match_id = p.match_id
JOIN teams th ON th.team_id = m.home_team_id
JOIN teams ta ON ta.team_id = m.away_team_id
JOIN seasons s ON s.season_id = m.season_id
JOIN leagues l ON l.league_id = s.league_id
JOIN match_odds mo ON mo.match_id = m.match_id AND LOWER(mo.selection) = p.side
WHERE p.rn = 1
GROUP BY l.code, m.match_id, th.name, ta.name, m.kickoff_utc, m.status, p.side, p.probability;
