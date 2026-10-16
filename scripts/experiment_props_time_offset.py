"""
Does a time-local league offset fix the pooled SOT model without going stale?

Pre-registered in docs/EXPERIMENT_REGISTRY.md ("Pre-registration, time-local
league offset for the pooled SOT model"), committed before this script was run
on real outcomes. Read-only: one SELECT, no writes.

M0 = the live model (existing leagues, no offset, no Bundesliga).
M3 = pooled with the Bundesliga plus a TRAILING league offset. For every row,
       offset = mean of y over that league's previous WINDOW rows with a
       strictly earlier kickoff;
     fewer than MIN_ROWS prior rows -> the training pool's mean of y (a
     constant, so those rows behave like the no-offset model).
     init_score = log(offset); mu = model output x offset. Same features,
     hyperparameters and 5-fold out-of-fold isotonic calibrators as live.
     The offset is causal: it uses only results known before each kickoff,
     which is what a live slate would have.

Rules R1, R3, R4 as in the props pre-registration; R2' is the sampling-error
calibration criterion (scripts/calibration_check.py).

    python scripts/experiment_props_time_offset.py --market SOT
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
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import KFold

from calibration_check import assess
from experiment_props_new_league import (
    B_CUTOFF, EXISTING, HYPERPARAMS, boot_ci, fit, ll_rows, load, predict_mu,
)
from generate_slate import PROPS_MARKETS, lgb

NEW_LEAGUE = "BUNDESLIGA"
WINDOW = 600      # prior league rows (about 300 matches)
MIN_ROWS = 200    # fewer prior rows than this -> pool-mean fallback


def trailing_offsets(df: pd.DataFrame, fallback: float, window: int = WINDOW,
                     min_rows: int = MIN_ROWS) -> pd.Series:
    """Per-row trailing league mean of y, using only rows with a strictly
    earlier kickoff in the same league. Index-aligned with df."""
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for _, g in df.groupby("league"):
        g = g.sort_values("kickoff")
        t = g["kickoff"].to_numpy()
        y = g["y"].to_numpy(dtype=float)
        csum = np.concatenate([[0.0], np.cumsum(y)])
        prior = np.searchsorted(t, t, side="left")  # rows with kickoff strictly before
        start = np.maximum(prior - window, 0)
        n = prior - start
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = (csum[prior] - csum[start]) / n
        out.loc[g.index] = np.where(n >= min_rows, mean, fallback)
    return out


def fit_time_offset(train: pd.DataFrame, feats: list[str], lines: list[float]):
    """(model, {line: isotonic}); train must carry an 'off' column."""
    off = train["off"].to_numpy()
    X, y = train[feats], train["y"]
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    oof = np.zeros(len(train))
    for tr, va in kf.split(train):
        m = lgb.LGBMRegressor(verbose=-1, **HYPERPARAMS).fit(
            X.iloc[tr], y.iloc[tr], init_score=np.log(off[tr]))
        oof[va] = np.maximum(m.predict(X.iloc[va]) * off[va], 0.05)
    cals = {}
    for line in lines:
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
        iso.fit(1 - poisson.cdf(np.floor(line), oof), (y.values > line).astype(int))
        cals[line] = iso
    model = lgb.LGBMRegressor(verbose=-1, **HYPERPARAMS).fit(X, y, init_score=np.log(off))
    return model, cals


def predict_time_offset(model, df: pd.DataFrame, feats: list[str]) -> np.ndarray:
    return np.maximum(model.predict(df[feats]) * df["off"].to_numpy(), 0.05)


def with_offsets(df: pd.DataFrame, train_mask: pd.Series) -> pd.DataFrame:
    fb = float(df.loc[train_mask, "y"].mean())
    return df.assign(off=trailing_offsets(df, fallback=fb))


def test_a(df: pd.DataFrame, market: str, holdout: str) -> dict:
    spec = PROPS_MARKETS[market]
    feats, lines = spec["features"], spec["lines"]
    new = df[df.league == NEW_LEAGUE]
    cutoff = new[new.season == holdout].kickoff.min()
    pool = df.league.isin(EXISTING + (NEW_LEAGUE,))
    train_mask = pool & (df.kickoff < cutoff)
    d = with_offsets(df, train_mask)
    train = d[train_mask]
    test = d[(d.league == NEW_LEAGUE) & (d.season == holdout)]
    hist = d[(d.league == NEW_LEAGUE) & (d.kickoff < cutoff)]
    model, cals = fit_time_offset(train, feats, lines)
    mu = predict_time_offset(model, test, feats)
    m1, _ = fit(train, feats, lines)
    mu1 = predict_mu(m1, test, feats)
    y, ids = test["y"].to_numpy(), test["match_id"].to_numpy()
    own = float(hist["y"].mean())
    ll3, ll1 = ll_rows(y, mu), ll_rows(y, mu1)
    ll_own = ll_rows(y, np.full(len(y), own))
    probs = {line: cals[line].predict(1 - poisson.cdf(np.floor(line), mu)) for line in lines}
    calib = {line: assess(probs[line], (y > line).astype(int), ids, n_boot=1000, seed=0) for line in lines}
    return {"holdout": holdout, "n_test": len(test), "n_train": len(train), "n_hist": len(hist),
            "mean_actual": float(y.mean()), "mean_pred": float(mu.mean()), "mean_pred_m1": float(mu1.mean()),
            "offset_mean": float(test["off"].mean()), "own_mean": own,
            "ll_m3": float(ll3.mean()), "ll_m1": float(ll1.mean()), "ll_own": float(ll_own.mean()),
            "gain_vs_own": boot_ci(ll_own - ll3, ids), "gain_vs_m1": boot_ci(ll1 - ll3, ids),
            "calib": calib}


def test_b(df: pd.DataFrame, market: str) -> dict:
    spec = PROPS_MARKETS[market]
    feats, lines = spec["features"], spec["lines"]
    cutoff = pd.Timestamp(B_CUTOFF, tz="UTC")
    base_mask = df.league.isin(EXISTING) & (df.kickoff < cutoff)
    pool_mask = df.league.isin(EXISTING + (NEW_LEAGUE,)) & (df.kickoff < cutoff)
    d = with_offsets(df, pool_mask)
    test = d[d.league.isin(EXISTING) & (d.kickoff >= cutoff)]
    y, ids = test["y"].to_numpy(), test["match_id"].to_numpy()
    m0, _ = fit(df[base_mask], feats, lines)
    m3, _ = fit_time_offset(d[pool_mask], feats, lines)
    diff = ll_rows(y, predict_time_offset(m3, test, feats)) - ll_rows(y, predict_mu(m0, test, feats))
    res = {"n_base": int(base_mask.sum()), "n_extra": int((pool_mask & (df.league == NEW_LEAGUE)).sum()),
           "n_test": len(test), "pooled": boot_ci(diff, ids), "by_league": {}}
    for lg in sorted(test.league.unique()):
        mask = (test.league == lg).to_numpy()
        res["by_league"][lg] = (int(mask.sum()),) + boot_ci(diff[mask], ids[mask])
    return res


def verdict(a1: dict, a2: dict, b: dict) -> dict:
    r1 = a1["gain_vs_own"][1] > 0 and a2["gain_vs_own"][0] > 0
    r2 = not any(r["fail"] for r in a1["calib"].values())
    r3 = b["pooled"][2] < 0.001
    r4 = abs(a1["mean_pred"] / a1["mean_actual"] - 1) <= 0.03
    return {"R1": r1, "R2'": r2, "R3": r3, "R4": r4, "promote": all((r1, r2, r3, r4))}


def report(market: str, a1: dict, a2: dict, b: dict) -> None:
    ok = lambda v: "PASS" if v else "FAIL"  # noqa: E731
    print(f"\n===== time-local league offset (window {WINDOW}, min {MIN_ROWS}), {NEW_LEAGUE} {market} =====")
    for a in (a1, a2):
        print(f"\nTest A, holdout {a['holdout']}: train {a['n_train']} rows (incl. {a['n_hist']} {NEW_LEAGUE}), "
              f"test {a['n_test']}")
        print(f"  mean actual {a['mean_actual']:.3f} | M3 predicted {a['mean_pred']:.3f} "
              f"({a['mean_pred'] / a['mean_actual'] - 1:+.1%}) | M1 predicted {a['mean_pred_m1']:.3f} "
              f"({a['mean_pred_m1'] / a['mean_actual'] - 1:+.1%}) | mean trailing offset {a['offset_mean']:.3f}")
        print(f"  log loss: M3 {a['ll_m3']:.4f}  M1 {a['ll_m1']:.4f}  own-mean {a['ll_own']:.4f}")
        for label, key in (("M3 vs own-mean", "gain_vs_own"), ("M3 vs M1", "gain_vs_m1")):
            g = a[key]
            print(f"  gain {label:15s} {g[0]:+.4f}  95% [{g[1]:+.4f}, {g[2]:+.4f}]")
    print(f"\nR2' on holdout {a1['holdout']} (99% intervals):")
    for line, r in a1["calib"].items():
        print(f"  Over {line}: shift {r['shift']:+.3f} [{r['shift_ci'][0]:+.3f}, {r['shift_ci'][1]:+.3f}]"
              f"{' FAIL' if r['shift_fail'] else ''}   slope {r['slope']:.3f} "
              f"[{r['slope_ci'][0]:.3f}, {r['slope_ci'][1]:.3f}]{' FAIL' if r['slope_fail'] else ''}")
    print(f"\nTest B: M3 (existing {b['n_base']} + {b['n_extra']} {NEW_LEAGUE}) vs live M0, "
          f"{b['n_test']} existing-league rows since {B_CUTOFF}")
    m, lo, hi = b["pooled"]
    print(f"  log-loss change M3 minus M0 (positive = worse): {m:+.5f}  95% [{lo:+.5f}, {hi:+.5f}]")
    for lg, (n, m, lo, hi) in b["by_league"].items():
        print(f"    {lg:8s} n={n:5d} {m:+.5f}  [{lo:+.5f}, {hi:+.5f}]")
    v = verdict(a1, a2, b)
    r2 = ok(v["R2'"])
    print(f"\nVerdict: R1 skill {ok(v['R1'])} | R2' calibration {r2} | "
          f"R3 non-inferiority {ok(v['R3'])} | R4 bias {ok(v['R4'])} -> "
          f"{'PROMOTE' if v['promote'] else 'DO NOT PROMOTE'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["SOT"])
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
