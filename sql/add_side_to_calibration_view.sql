-- One-off migration for the already-running database (fresh installs get
-- this via schema.sql). Purely additive -- CREATE OR REPLACE VIEW, no
-- data touched.
--
-- v_calibration previously grouped only by (market, league, prob_bucket),
-- merging home/draw/away (or over/under) predictions into one calibration
-- bucket. Dixon-Coles is known to systematically misprice draws
-- specifically -- averaging them into the same bucket as home/away wins
-- hides exactly the bias worth seeing. Every market has a real, non-null
-- side value (checked live), so splitting by side is useful everywhere,
-- not just for 1X2 draws: also shows whether CORNERS/SOT "over" and
-- "under" calibrate differently.
--
--     psql "$FUTBOL_DSN" -f sql/add_side_to_calibration_view.sql

-- CREATE OR REPLACE VIEW can only append new columns, not insert them
-- mid-list (postgres rejects that as an implicit rename) -- side goes
-- last, not next to market, for that reason.
CREATE OR REPLACE VIEW futbol.v_calibration AS
SELECT
    p.market,
    l.code AS league,
    width_bucket(p.probability, 0.0, 1.0, 10) AS prob_bucket,      -- decile bins
    ROUND(AVG(p.probability)::numeric, 4)     AS avg_stated_prob,
    ROUND(AVG((g.outcome = 'hit')::int)::numeric, 4) AS realized_rate,
    COUNT(*) AS n,
    p.side
FROM futbol.predictions p
JOIN futbol.prediction_grades g USING (prediction_id)
JOIN futbol.matches m USING (match_id)
JOIN futbol.seasons s USING (season_id)
JOIN futbol.leagues l USING (league_id)
WHERE g.outcome <> 'void'
GROUP BY p.market, p.side, l.code, prob_bucket;
