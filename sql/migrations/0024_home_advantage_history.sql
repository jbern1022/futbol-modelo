-- Home-advantage (Dixon-Coles gamma) drift across seasons. gamma is fit
-- on every live retrain (scripts/generate_slate.py's fit_dixon_coles) but
-- was never persisted -- model_versions only stores hyperparameters
-- (xi/reg), and even that table is a "latest known state" row per league
-- (ON CONFLICT ... DO UPDATE), not an append-only history, so there was
-- nowhere a per-season value could actually accumulate into a series.
--
-- One row per (league, season): gamma fit using ONLY that season's
-- finished matches, via scripts/backfill_home_advantage.py -- a separate,
-- deliberately isolated fit from the live model's fit_dixon_coles (which
-- trains on all available history for the best live prediction, not one
-- season at a time). Re-running the backfill for an in-progress season
-- upserts that season's row as more matches complete.
CREATE TABLE futbol.home_advantage_history (
    league       TEXT NOT NULL,
    season       TEXT NOT NULL,
    gamma        DOUBLE PRECISION NOT NULL,
    n_matches    INT NOT NULL,
    fitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (league, season)
);

GRANT SELECT ON futbol.home_advantage_history TO futbol_ro;
