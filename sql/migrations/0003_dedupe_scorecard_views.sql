-- Excludes duplicate predictions from v_season_scorecard / v_calibration
-- without touching the ledger. See the [PARTIAL] duplicate-slate ticket:
-- match_id 4456 got slated twice (three weeks apart, under two different
-- model_version_id rows) before generate_for_fixture() had a guard
-- against it, producing 14 exact-duplicate prediction pairs that are
-- already graded -- prediction_grades has no mechanism to void an
-- already-graded row, so the raw predictions/prediction_grades tables
-- stay exactly as they are, permanently (every row still exists, still
-- queryable via /predictions/{id}). This only changes what the two
-- season-summary VIEWS count: for each natural key (match, market,
-- side, line, subject), only the earliest prediction_id is counted.
-- General by construction -- protects against any future duplicate
-- that somehow slips past the generator's new guard, not just this one
-- match.

CREATE OR REPLACE VIEW v_graded_predictions AS
SELECT prediction_id, match_id, market, side, line, subject_team_id,
       subject_player_id, probability, outcome, league, season
FROM (
    SELECT p.prediction_id, p.match_id, p.market, p.side, p.line,
           p.subject_team_id, p.subject_player_id, p.probability,
           g.outcome, l.code AS league, s.label AS season,
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
    side
FROM v_graded_predictions
GROUP BY market, side, league, prob_bucket;

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
    )::numeric, 4)                                  AS log_loss
FROM v_graded_predictions
GROUP BY league, season, market
ORDER BY league, season, market;
