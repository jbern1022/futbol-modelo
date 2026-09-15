-- Closing-line-value (CLV): "our predictions beat the closing line" is
-- the strongest possible version of this project's calibration claim --
-- did the model's stated probability, locked before kickoff, actually
-- land closer to the truth than the market's own final (closing) price?
--
-- Purely a read-side view over data that already exists: v_odds_movement
-- (migration 0019) already computes opening/closing per (match,
-- bookmaker, market, selection); this joins its closing side against
-- our own graded 1X2 predictions. No new ingestion, no new API calls --
-- match_odds_history only fills in as fetch_and_store_odds() actually
-- runs (currently ad hoc, not on any recurring schedule -- see the
-- ticket comment on rather this should be scheduled, a real API-quota
-- cost decision, not made here). Selections differ in case ("Home" vs
-- "home"), hence the lower() join.
CREATE OR REPLACE VIEW futbol.v_closing_line_value AS
SELECT
    p.prediction_id, p.match_id, p.statement, p.side,
    p.probability AS our_probability,
    AVG(m.closing_probability) AS avg_closing_market_probability,
    p.probability - AVG(m.closing_probability) AS edge_vs_closing,
    g.outcome, g.actual_value
FROM futbol.predictions p
JOIN futbol.prediction_grades g ON g.prediction_id = p.prediction_id
JOIN futbol.v_odds_movement m
  ON m.match_id = p.match_id AND m.market = p.market
 AND lower(m.selection) = p.side
WHERE p.market = '1X2'
GROUP BY p.prediction_id, p.match_id, p.statement, p.side,
         p.probability, g.outcome, g.actual_value;

GRANT SELECT ON futbol.v_closing_line_value TO futbol_ro;
