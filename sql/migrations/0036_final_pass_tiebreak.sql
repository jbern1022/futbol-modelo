-- ADR-010: close-to-kickoff "final pass" for PLAYER_GOALS/PLAYER_SAVES
-- (Todoist: "futbol-modelo: lineup/injury news as a model feature").
-- scripts/generate_slate.py's generate_final_pass_for_fixture() writes
-- a SECOND, more-informed prediction row for a fixture that already
-- has an original slate -- same natural key (match/market/side/line/
-- subject), different model_versions.model_name
-- ('player_props_lineup_confirmed_v1'). v_graded_predictions' existing
-- dedupe (earliest-prediction_id-wins, added for the real duplicate-
-- slate incident ADR-002/0003_dedupe_scorecard_views.sql guards
-- against) needs to prefer the final-pass row instead, since here a
-- second row is intentional and strictly more informed, not a bug.
-- Two rows under the SAME model_name still resolve earliest-wins, so
-- the original protection is unchanged for the case it exists for.
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
               ORDER BY (mv.model_name = 'player_props_lineup_confirmed_v1') DESC,
                        p.prediction_id
           ) AS rn
    FROM predictions p
    JOIN model_versions mv ON mv.model_version_id = p.model_version_id
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
