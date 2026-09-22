-- Adds a sport level above league to v_graded_predictions,
-- v_calibration, and v_season_scorecard (Todoist: "Per-sport
-- calibration views and Track Record sport filter" -- "v_calibration
-- and v_season_scorecard group by league/market -- they need a sport
-- level above that").
--
-- leagues.sport already exists (soccer/basketball/football) and is
-- already joined in v_graded_predictions' underlying query -- this is
-- purely exposing a column that was already available, not new
-- ingestion or modeling work.
--
-- CREATE OR REPLACE VIEW can only append new columns, not insert them
-- mid-list (postgres rejects that as an implicit rename) -- sport goes
-- last in each view, same reason side was appended last in
-- sql/add_side_to_calibration_view.sql rather than placed next to
-- market.
CREATE OR REPLACE VIEW v_graded_predictions AS
SELECT prediction_id, match_id, market, side, line, subject_team_id,
       subject_player_id, probability, outcome, league, season, sport
FROM (
    SELECT p.prediction_id, p.match_id, p.market, p.side, p.line,
           p.subject_team_id, p.subject_player_id, p.probability,
           g.outcome, l.code AS league, s.label AS season, l.sport AS sport,
           ROW_NUMBER() OVER (
               PARTITION BY p.match_id, p.market, p.side, p.line,
                            p.subject_team_id, p.subject_player_id
               ORDER BY p.prediction_id
           ) AS rn
    FROM predictions p
    JOIN prediction_grades g USING (prediction_id)
    JOIN matches m USING (match_id)
    JOIN seasons s USING (season_id)
    JOIN leagues l USING (league_id)
    WHERE g.outcome <> 'void'
) ranked
WHERE rn = 1;

CREATE OR REPLACE VIEW v_calibration AS
SELECT
    market,
    league,
    width_bucket(probability, 0.0, 1.0, 10) AS prob_bucket,
    ROUND(AVG(probability)::numeric, 4)     AS avg_stated_prob,
    ROUND(AVG((outcome = 'hit')::int)::numeric, 4) AS realized_rate,
    COUNT(*) AS n,
    side,
    sport
FROM v_graded_predictions
GROUP BY market, side, league, prob_bucket, sport;

CREATE OR REPLACE VIEW v_season_scorecard AS
SELECT
    league,
    season,
    market,
    COUNT(*)                                        AS n_predictions,
    ROUND(AVG((outcome='hit')::int)::numeric, 4)    AS hit_rate,
    ROUND(AVG(probability)::numeric, 4)             AS avg_confidence,
    ROUND(AVG(POWER(probability - (outcome='hit')::int, 2))::numeric, 4) AS brier,
    ROUND(AVG(
        - ( (outcome='hit')::int * LN(GREATEST(probability, 1e-9))
          + (1-(outcome='hit')::int) * LN(GREATEST(1-probability, 1e-9)) )
    )::numeric, 4)                                  AS log_loss,
    sport
FROM v_graded_predictions
GROUP BY league, season, market, sport
ORDER BY league, season, market;
