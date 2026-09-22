-- Bootstrap confidence intervals on Dixon-Coles' fitted attack/defence
-- ratings (Todoist: "Uncertainty intervals on team attack/defence
-- ratings"; src/models/team_ratings.py has the statistical core).
--
-- Full-recompute table, not append-only: scripts/compute_team_ratings.py
-- truncates and rewrites this every run, matching the "retrain from
-- scratch" pattern used for model_versions/bankroll_simulation. This is
-- a CURRENT snapshot (fit on all available history with the live
-- model's own time-decay weighting), not a per-season series -- unlike
-- home_advantage_history, which deliberately isolates one season at a
-- time (see that migration's comment for why the two differ).
CREATE TABLE IF NOT EXISTS team_ratings (
    league          TEXT NOT NULL,
    team            TEXT NOT NULL,
    atk             NUMERIC(6,4) NOT NULL,
    atk_ci_low      NUMERIC(6,4) NOT NULL,
    atk_ci_high     NUMERIC(6,4) NOT NULL,
    dfn             NUMERIC(6,4) NOT NULL,
    dfn_ci_low      NUMERIC(6,4) NOT NULL,
    dfn_ci_high     NUMERIC(6,4) NOT NULL,
    n_boot_samples  INT NOT NULL,
    n_matches       INT NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (league, team)
);

GRANT SELECT ON futbol.team_ratings TO futbol_ro;
