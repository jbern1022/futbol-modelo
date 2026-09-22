-- Paper-trading / bankroll simulation (Todoist: "futbol-modelo:
-- paper-trading / bankroll simulation", Phase 3). A real ROI curve
-- denominated in money, not percentages -- flat-stake v1, walking
-- graded predictions in kickoff order against the real bookmaker odds
-- available at each prediction's own locked_at (the honest bettable
-- price, not the closing line -- betting at closing would be
-- unrealistic, the market's already moved by then).
--
-- Full-recompute table, not append-only: scripts/simulate_bankroll.py
-- truncates and rewrites this every run (matching the "no saved
-- checkpoints, retrain from scratch" pattern used everywhere else in
-- this project) rather than accumulating history-of-histories. run_at
-- marks which run produced the current rows.
CREATE TABLE IF NOT EXISTS bankroll_simulation (
    prediction_id     BIGINT PRIMARY KEY REFERENCES predictions(prediction_id),
    match_id          INT NOT NULL REFERENCES matches(match_id),
    kickoff_utc       TIMESTAMPTZ NOT NULL,
    market            TEXT NOT NULL,
    side              TEXT NOT NULL,
    model_probability NUMERIC(6,5) NOT NULL,
    decimal_odds      NUMERIC(8,3) NOT NULL,
    stake             NUMERIC(10,2) NOT NULL,
    outcome           TEXT NOT NULL,
    profit            NUMERIC(10,2) NOT NULL,
    bankroll_after    NUMERIC(12,2) NOT NULL,
    run_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bankroll_simulation_kickoff
    ON bankroll_simulation(kickoff_utc);

GRANT SELECT ON futbol.bankroll_simulation TO futbol_ro;
