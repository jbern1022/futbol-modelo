"""
Production-configuration check for a new league's props: the new league sits
in the training pool, with no league term (M1).

Pre-registered in docs/EXPERIMENT_REGISTRY.md ("Pre-registration, Bundesliga in
the training pool with no offset"), committed before this script produced a
result, with the already-known SOT numbers disclosed there. Read-only.

  Test A: train on existing leagues + Bundesliga rows before the holdout
          season, score the Bundesliga holdout (2025-26 primary, 2024-25).
  Test B: M1 (existing + Bundesliga, before 2025-08-01) vs M0 (existing only,
          the current live model) on existing-league rows since 2025-08-01.

    python scripts/experiment_props_pool_only.py --market SOT
    python scripts/experiment_props_pool_only.py --market CORNERS
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

from experiment_props_league_offset import calibration
from experiment_props_new_league import B_CUTOFF, EXISTING, boot_ci, fit, ll_rows, load, predict_mu
from generate_slate import PROPS_MARKETS, lgb

NEW_LEAGUE = "BUNDESLIGA"


def test_a(df: pd.DataFrame, market: str, holdout: str) -> dict:
    spec = PROPS_MARKETS[market]
    feats, lines = spec["features"], spec["lines"]
    new = df[df.league == NEW_LEAGUE]
    test = new[new.season == holdout]
    cutoff = test.kickoff.min()
    train = df[df.league.isin(EXISTING + (NEW_LEAGUE,)) & (df.kickoff < cutoff)]
    hist = new[new.kickoff < cutoff]
    model, cals = fit(train, feats, lines)
    mu = predict_mu(model, test, feats)
    y, ids = test["y"].to_numpy(), test["match_id"].to_numpy()
    own = float(hist["y"].mean())
    ll_m = ll_rows(y, mu)
    ll_own = ll_rows(y, np.full(len(y), own))
    return {"holdout": holdout, "n_test": len(test), "n_train": len(train), "n_hist": len(hist),
            "mean_pred": float(mu.mean()), "mean_actual": float(y.mean()), "own_mean": own,
            "ll_model": float(ll_m.mean()), "ll_own": float(ll_own.mean()),
            "gain_vs_own": boot_ci(ll_own - ll_m, ids), "calib": calibration(mu, y, cals, lines)}


def test_b(df: pd.DataFrame, market: str) -> dict:
    spec = PROPS_MARKETS[market]
    feats, lines = spec["features"], spec["lines"]
    cutoff = pd.Timestamp(B_CUTOFF, tz="UTC")
    base = df[df.league.isin(EXISTING) & (df.kickoff < cutoff)]
    extra = df[(df.league == NEW_LEAGUE) & (df.kickoff < cutoff)]
    test = df[df.league.isin(EXISTING) & (df.kickoff >= cutoff)]
    y, ids = test["y"].to_numpy(), test["match_id"].to_numpy()
    m0, _ = fit(base, feats, lines)
    m1, _ = fit(pd.concat([base, extra], ignore_index=True), feats, lines)
    diff = ll_rows(y, predict_mu(m1, test, feats)) - ll_rows(y, predict_mu(m0, test, feats))
    res = {"n_base": len(base), "n_extra": len(extra), "n_test": len(test),
           "pooled": boot_ci(diff, ids), "by_league": {}}
    for lg in sorted(test.league.unique()):
        mask = (test.league == lg).to_numpy()
        res["by_league"][lg] = (int(mask.sum()),) + boot_ci(diff[mask], ids[mask])
    return res


def verdict(a1: dict, a2: dict, b: dict) -> dict:
    r1 = a1["gain_vs_own"][1] > 0 and a2["gain_vs_own"][0] > 0
    r2 = True
    for d in a1["calib"].values():
        if not d["cal_gap"] <= 0.05:
            r2 = False
        if any(n >= 100 and abs(a - s) > 0.07 for _, n, s, a in d["bands"]):
            r2 = False
    r3 = b["pooled"][2] < 0.001
    r4 = abs(a1["mean_pred"] / a1["mean_actual"] - 1) <= 0.03
    return {"R1": r1, "R2": r2, "R3": r3, "R4": r4, "promote": all((r1, r2, r3, r4))}


def report(market: str, a1: dict, a2: dict, b: dict) -> None:
    ok = lambda v: "PASS" if v else "FAIL"  # noqa: E731
    print(f"\n===== {NEW_LEAGUE} {market}: new league in the pool, no offset (M1) =====")
    for a in (a1, a2):
        print(f"\nTest A, holdout {a['holdout']}: train {a['n_train']} rows (incl. {a['n_hist']} {NEW_LEAGUE}), "
              f"test {a['n_test']}")
        print(f"  mean actual {a['mean_actual']:.3f} | predicted {a['mean_pred']:.3f} "
              f"({a['mean_pred'] / a['mean_actual'] - 1:+.1%}) | own-history mean {a['own_mean']:.3f}")
        g = a["gain_vs_own"]
        print(f"  log loss: model {a['ll_model']:.4f}  own-mean {a['ll_own']:.4f}  "
              f"gain {g[0]:+.4f}  95% [{g[1]:+.4f}, {g[2]:+.4f}]")
    print(f"\nCalibration, holdout {a1['holdout']}:")
    for line, d in a1["calib"].items():
        print(f"  Over {line}: base rate {d['base_rate']:.3f}  calibrated quartile gap {d['cal_gap']:.3f}")
        for name, n, s, act in d["bands"]:
            flag = "  <-- >0.07" if n >= 100 and abs(act - s) > 0.07 else ""
            print(f"      band {name}: n={n:4d} stated {s:.3f} realized {act:.3f} gap {act - s:+.3f}{flag}")
    print(f"\nTest B: M1 (existing {b['n_base']} + {b['n_extra']} {NEW_LEAGUE}) vs live M0, "
          f"{b['n_test']} existing-league rows since {B_CUTOFF}")
    m, lo, hi = b["pooled"]
    print(f"  log-loss change M1 minus M0 (positive = worse): {m:+.5f}  95% [{lo:+.5f}, {hi:+.5f}]")
    for lg, (n, m, lo, hi) in b["by_league"].items():
        print(f"    {lg:8s} n={n:5d} {m:+.5f}  [{lo:+.5f}, {hi:+.5f}]")
    v = verdict(a1, a2, b)
    print(f"\nVerdict: R1 skill {ok(v['R1'])} | R2 calibration {ok(v['R2'])} | R3 non-inferiority {ok(v['R3'])} "
          f"| R4 bias {ok(v['R4'])} -> {'PROMOTE' if v['promote'] else 'DO NOT PROMOTE'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["CORNERS", "SOT"])
    ap.add_argument("--holdouts", nargs=2, default=["2025-26", "2024-25"], metavar=("PRIMARY", "SECOND"))
    args = ap.parse_args()
    if lgb is None:
        raise SystemExit("lightgbm not installed")

    conn = psycopg2.connect(os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol"))
    conn.set_session(readonly=True)
    cur = conn.cursor()
    df = load(cur, args.market, EXISTING + (NEW_LEAGUE,))
    conn.close()
    print(f"{len(df)} rows: " + ", ".join(f"{k} {v}" for k, v in df.league.value_counts().items()))

    a1 = test_a(df, args.market, args.holdouts[0])
    a2 = test_a(df, args.market, args.holdouts[1])
    b = test_b(df, args.market)
    report(args.market, a1, a2, b)


if __name__ == "__main__":
    main()
