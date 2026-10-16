"""
Does an xG-free props model fix the live CORNERS/SOT predictions for MLS?

Pre-registered in docs/EXPERIMENT_REGISTRY.md ("Pre-registration, an xG-free
props model for MLS"), committed before this script was run. Read-only.

MLS has no xG. The live fit_props_model drops every row with a missing feature
(dropna), so MLS is never in the training set, yet MLS fixtures are scored with
xg_for_r5 / xg_against_r5 missing.

  A  live configuration: market's league set without MLS, all features;
     MLS scored with xG missing
  B  pooled model trained WITHOUT the two xG features on the league set plus MLS
  C  MLS-only model without the xG features

    python scripts/experiment_props_mls_no_xg.py --market SOT
    python scripts/experiment_props_mls_no_xg.py --market CORNERS
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

from calibration_check import assess
from experiment_props_new_league import boot_ci, fit, ll_rows, predict_mu
from generate_slate import PROPS_MARKETS, lgb

MLS = "MLS"


def load_all(cur, market: str) -> pd.DataFrame:
    """Every team-match row with n_prior >= 5, features kept as-is (xG may be NaN)."""
    spec = PROPS_MARKETS[market]
    feats = spec["features"]
    cols = ", ".join(f"f.{c}" for c in feats)
    leagues = sorted(set(spec["leagues"]) | {MLS})
    cur.execute(
        f"""SELECT {cols}, tms.{spec['target_col']} AS y, l.code AS league, s.label AS season,
                   f.match_id, f.kickoff_utc
            FROM futbol.team_match_features f
            JOIN futbol.matches m ON m.match_id = f.match_id
            JOIN futbol.seasons s ON s.season_id = m.season_id
            JOIN futbol.leagues l ON l.league_id = s.league_id
            JOIN futbol.team_match_stats tms
              ON tms.match_id = f.match_id AND tms.team_id = f.team_id
            WHERE l.code = ANY(%s) AND tms.{spec['target_col']} IS NOT NULL AND f.n_prior >= 5""",
        (leagues,))
    df = pd.DataFrame(cur.fetchall(), columns=feats + ["y", "league", "season", "match_id", "kickoff"])
    for c in feats + ["y"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["is_home"] = df["is_home"].astype(int)
    df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
    return df.dropna(subset=["y"]).reset_index(drop=True)


def run_holdout(df: pd.DataFrame, market: str, holdout: str) -> dict:
    spec = PROPS_MARKETS[market]
    full = spec["features"]
    noxg = [f for f in full if not f.startswith("xg_")]
    lines = spec["lines"]
    live_leagues = set(spec["leagues"]) - {MLS}

    mls = df[df.league == MLS]
    test = mls[(mls.season == holdout)].dropna(subset=noxg)
    cutoff = test.kickoff.min()
    before = df[df.kickoff < cutoff]

    train_a = before[before.league.isin(live_leagues)].dropna(subset=full)
    train_b = before[before.league.isin(live_leagues | {MLS})].dropna(subset=noxg)
    train_c = before[before.league == MLS].dropna(subset=noxg)

    y, ids = test["y"].to_numpy(), test["match_id"].to_numpy()
    out = {"holdout": holdout, "n_test": len(test), "mean_actual": float(y.mean()),
           "n_train": {"A": len(train_a), "B": len(train_b), "C": len(train_c)}, "mu": {}, "ll": {}, "calib": {}}
    for tag, train, feats in (("A", train_a, full), ("B", train_b, noxg), ("C", train_c, noxg)):
        model, cals = fit(train, feats, lines)
        mu = predict_mu(model, test, feats)
        out["mu"][tag] = float(mu.mean())
        out["ll"][tag] = ll_rows(y, mu)
        probs = {line: cals[line].predict(1 - poisson.cdf(np.floor(line), mu)) for line in lines}
        out["calib"][tag] = {line: assess(probs[line], (y > line).astype(int), ids, n_boot=1000, seed=0)
                             for line in lines}
    out["ids"] = ids
    out["gain_b_vs_a"] = boot_ci(out["ll"]["A"] - out["ll"]["B"], ids)
    out["gain_c_vs_a"] = boot_ci(out["ll"]["A"] - out["ll"]["C"], ids)
    out["gain_b_vs_c"] = boot_ci(out["ll"]["C"] - out["ll"]["B"], ids)
    return out


def verdict(p: dict, s: dict) -> dict:
    r1 = p["gain_b_vs_a"][1] > 0 and s["gain_b_vs_a"][0] > 0
    r2 = not any(r["fail"] for r in p["calib"]["B"].values())
    r4 = abs(p["mu"]["B"] / p["mean_actual"] - 1) <= 0.03
    return {"R1": r1, "R2'": r2, "R4": r4, "recommend": all((r1, r2, r4))}


def report(market: str, p: dict, s: dict) -> None:
    ok = lambda v: "PASS" if v else "FAIL"  # noqa: E731
    print(f"\n===== MLS {market}: live (A) vs xG-free pooled (B) vs xG-free MLS-only (C) =====")
    for r in (p, s):
        print(f"\nHoldout MLS {r['holdout']}: test {r['n_test']} team-matches; train rows "
              f"A {r['n_train']['A']}, B {r['n_train']['B']}, C {r['n_train']['C']}")
        print(f"  mean actual {r['mean_actual']:.3f} | predicted A {r['mu']['A']:.3f} "
              f"({r['mu']['A'] / r['mean_actual'] - 1:+.1%}) | B {r['mu']['B']:.3f} "
              f"({r['mu']['B'] / r['mean_actual'] - 1:+.1%}) | C {r['mu']['C']:.3f} "
              f"({r['mu']['C'] / r['mean_actual'] - 1:+.1%})")
        print(f"  Poisson log loss: A {r['ll']['A'].mean():.4f}  B {r['ll']['B'].mean():.4f}  "
              f"C {r['ll']['C'].mean():.4f}")
        for label, key in (("A minus B (positive = B better)", "gain_b_vs_a"),
                           ("A minus C", "gain_c_vs_a"), ("C minus B (positive = B better)", "gain_b_vs_c")):
            g = r[key]
            print(f"  {label:34s} {g[0]:+.4f}  95% [{g[1]:+.4f}, {g[2]:+.4f}]")
    print(f"\nR2' on MLS {p['holdout']} (99% intervals):")
    for tag in ("A", "B", "C"):
        res = p["calib"][tag]
        print(f"  model {tag}: {'FAIL' if any(r['fail'] for r in res.values()) else 'pass'}")
        for line, r in res.items():
            print(f"    Over {line}: shift {r['shift']:+.3f} [{r['shift_ci'][0]:+.3f}, {r['shift_ci'][1]:+.3f}]"
                  f"{' FAIL' if r['shift_fail'] else ''}   slope {r['slope']:.3f} "
                  f"[{r['slope_ci'][0]:.3f}, {r['slope_ci'][1]:.3f}]{' FAIL' if r['slope_fail'] else ''}")
    v = verdict(p, s)
    r2 = ok(v["R2'"])
    print(f"\nVerdict (candidate B): R1 skill {ok(v['R1'])} | R2' calibration {r2} "
          f"| R4 bias {ok(v['R4'])} -> {'RECOMMEND B FOR MLS' if v['recommend'] else 'DO NOT RECOMMEND'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["CORNERS", "SOT"])
    args = ap.parse_args()
    if lgb is None:
        raise SystemExit("lightgbm not installed")
    conn = psycopg2.connect(os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol"))
    conn.set_session(readonly=True)
    cur = conn.cursor()
    df = load_all(cur, args.market)
    conn.close()
    print(f"{len(df)} rows: " + ", ".join(f"{k} {v}" for k, v in df.league.value_counts().items()))
    primary = run_holdout(df, args.market, "2026")
    second = run_holdout(df, args.market, "2025")
    report(args.market, primary, second)


if __name__ == "__main__":
    main()
