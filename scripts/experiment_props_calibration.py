"""
Apply the sampling-error calibration criterion (scripts/calibration_check.py)
to the Bundesliga props configurations, and report the criterion's own
operating characteristics by simulation.

Pre-registered in docs/EXPERIMENT_REGISTRY.md ("Pre-registration,
sampling-error calibration criterion"). Read-only.

  --simulate   needs probabilities only: invents outcomes under known
               calibration and reports how often the criterion fails. It
               never reads or prints a real outcome.
  --evaluate   applies the criterion to the real Bundesliga outcomes.

Configurations (all scored on Bundesliga holdout seasons, live features,
hyperparameters and 5-fold out-of-fold isotonic calibrators):
  pool     existing leagues + earlier Bundesliga rows, no league term (M1;
           the production configuration)
  outside  existing leagues only (the original out-of-league test)
  offset   pool plus the league-mean offset (M2)

    python scripts/experiment_props_calibration.py --simulate
    python scripts/experiment_props_calibration.py --evaluate
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson

from calibration_check import assess, logit
from experiment_props_league_offset import fit_offset, predict_offset
from experiment_props_new_league import EXISTING, fit, load, predict_mu
from generate_slate import PROPS_MARKETS, lgb

NEW_LEAGUE = "BUNDESLIGA"


def line_probs(df: pd.DataFrame, market: str, holdout: str, config: str):
    """(test rows, {line: calibrated P(over)}) for one configuration."""
    spec = PROPS_MARKETS[market]
    feats, lines = spec["features"], spec["lines"]
    new = df[df.league == NEW_LEAGUE]
    test = new[new.season == holdout]
    cutoff = test.kickoff.min()
    leagues = EXISTING if config == "outside" else EXISTING + (NEW_LEAGUE,)
    train = df[df.league.isin(leagues) & (df.kickoff < cutoff)]
    if config == "offset":
        model, cals, means = fit_offset(train, feats, lines)
        mu = predict_offset(model, means, test, feats)
    else:
        model, cals = fit(train, feats, lines)
        mu = predict_mu(model, test, feats)
    return test, {line: cals[line].predict(1 - poisson.cdf(np.floor(line), mu)) for line in lines}


def market_fail(probs: dict, outcomes: dict, ids: np.ndarray, n_boot: int, seed: int) -> tuple[bool, dict]:
    res = {line: assess(probs[line], outcomes[line], ids, n_boot=n_boot, seed=seed) for line in probs}
    return any(r["fail"] for r in res.values()), res


def main() -> None:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--simulate", action="store_true")
    mode.add_argument("--evaluate", action="store_true")
    ap.add_argument("--sims", type=int, default=200)
    ap.add_argument("--boot", type=int, default=1000)
    args = ap.parse_args()
    if lgb is None:
        raise SystemExit("lightgbm not installed")

    conn = psycopg2.connect(os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol"))
    conn.set_session(readonly=True)
    cur = conn.cursor()
    # Different feature sets per market, so one frame each.
    frames = {m: load(cur, m, EXISTING + (NEW_LEAGUE,)) for m in ("CORNERS", "SOT")}
    conn.close()

    if args.simulate:
        simulate_all(frames, args.sims, args.boot)
    else:
        evaluate_all(frames, args.boot)


def simulate_all(frames: dict, n_sims: int, n_boot: int) -> None:
    rng = np.random.default_rng(12345)
    scenarios = [("perfect", 0.0, 1.0), ("shift +0.10", 0.10, 1.0), ("shift +0.15", 0.15, 1.0),
                 ("shift +0.25", 0.25, 1.0), ("shift -0.25", -0.25, 1.0),
                 ("slope 0.80", 0.0, 0.80), ("slope 0.70", 0.0, 0.70), ("slope 1.25", 0.0, 1.25)]
    for market, df in frames.items():
        test, probs = line_probs(df, market, "2025-26", "pool")
        ids = test["match_id"].to_numpy()
        print(f"\n{market}: {len(test)} rows, lines {list(probs)}; {n_sims} simulations x {n_boot} bootstrap draws")
        print(f"  {'scenario':12s} {'market fails':>13s}   per-line fail rates")
        for name, shift, slope in scenarios:
            hits = 0
            line_hits = {line: 0 for line in probs}
            for s in range(n_sims):
                outcomes = {}
                for line, p in probs.items():
                    true_p = 1 / (1 + np.exp(-(shift + slope * logit(p))))
                    outcomes[line] = (rng.random(len(p)) < true_p).astype(int)
                failed, res = market_fail(probs, outcomes, ids, n_boot, seed=s)
                hits += failed
                for line, r in res.items():
                    line_hits[line] += r["fail"]
            print(f"  {name:12s} {hits / n_sims:>12.1%}   "
                  + "  ".join(f"{line}: {line_hits[line] / n_sims:.1%}" for line in probs))


def evaluate_all(frames: dict, n_boot: int) -> None:
    for market, df in frames.items():
        evaluate_market(df, market, n_boot)


def evaluate_market(df: pd.DataFrame, market: str, n_boot: int) -> None:
    for config in ("pool", "outside", "offset"):
        if config == "offset" and market == "CORNERS":
            continue
        for holdout in ("2025-26", "2024-25"):
            test, probs = line_probs(df, market, holdout, config)
            ids = test["match_id"].to_numpy()
            y = test["y"].to_numpy()
            outcomes = {line: (y > line).astype(int) for line in probs}
            failed, res = market_fail(probs, outcomes, ids, n_boot, seed=0)
            tag = "GATING" if (config == "pool" and holdout == "2025-26") else "context"
            print(f"\n{market} / {config} / {holdout} [{tag}]  n={len(test)}  -> {'FAIL' if failed else 'PASS'}")
            for line, r in res.items():
                print(f"  Over {line}: shift {r['shift']:+.3f} [{r['shift_ci'][0]:+.3f}, {r['shift_ci'][1]:+.3f}]"
                      f"{' FAIL' if r['shift_fail'] else ''}   slope {r['slope']:.3f} "
                      f"[{r['slope_ci'][0]:.3f}, {r['slope_ci'][1]:.3f}]{' FAIL' if r['slope_fail'] else ''}")


if __name__ == "__main__":
    main()
