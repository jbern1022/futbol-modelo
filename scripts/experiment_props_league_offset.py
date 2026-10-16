"""
Does a league-level offset fix the pooled SOT model's Bundesliga bias?

Pre-registered in docs/EXPERIMENT_REGISTRY.md ("Pre-registration, league-level
offset for the pooled SOT model"), committed before this script produced a
result. Read-only: one SELECT, no writes.

M0 = the live model (existing leagues, no offset, no Bundesliga).
M1 = pooled with the Bundesliga, no offset (the model that failed R2/R3).
M2 = pooled with the Bundesliga plus a league-level offset:
       init_score = log(mean y of that league's training rows), and
       mu = model output x that league's mean at prediction.
     Same features, hyperparameters and 5-fold out-of-fold isotonic
     calibrators as the live pipeline.

    python scripts/experiment_props_league_offset.py --market SOT
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

from experiment_props_new_league import (
    B_CUTOFF, EXISTING, HYPERPARAMS, boot_ci, fit, ll_rows, load, predict_mu,
)
from generate_slate import PROPS_MARKETS, lgb

NEW_LEAGUE = "BUNDESLIGA"


def league_means(train: pd.DataFrame) -> dict[str, float]:
    return train.groupby("league")["y"].mean().to_dict()


def fit_offset(train: pd.DataFrame, feats: list[str], lines: list[float]):
    """(model, {line: isotonic}, league_means) for the league-offset model."""
    means = league_means(train)
    off = train["league"].map(means).to_numpy()
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
    return model, cals, means


def predict_offset(model, means: dict[str, float], df: pd.DataFrame, feats: list[str]) -> np.ndarray:
    """predict() excludes init_score, so scale by the league mean."""
    return np.maximum(model.predict(df[feats]) * df["league"].map(means).to_numpy(), 0.05)


def calibration(mu: np.ndarray, y: np.ndarray, cals: dict, lines: list[float]) -> dict:
    out = {}
    for line in lines:
        cal = cals[line].predict(1 - poisson.cdf(np.floor(line), mu))
        actual = (y > line).astype(int)
        try:
            qb = pd.qcut(cal, q=4, duplicates="drop")
            g = pd.DataFrame({"b": qb, "s": cal, "a": actual}).groupby("b", observed=True).agg(
                s=("s", "mean"), a=("a", "mean"))
            qgap = float((g["a"] - g["s"]).abs().mean())
        except ValueError:
            qgap = float("nan")
        band = pd.cut(cal, np.arange(0, 1.0001, 0.1), include_lowest=True)
        g = pd.DataFrame({"b": band, "s": cal, "a": actual}).groupby("b", observed=True).agg(
            n=("a", "size"), s=("s", "mean"), a=("a", "mean"))
        out[line] = {"cal_gap": qgap, "base_rate": float(actual.mean()),
                     "bands": [(f"{iv.left:.1f}-{iv.right:.1f}", int(r.n), float(r.s), float(r.a))
                               for iv, r in g.iterrows()]}
    return out


def test_a(df: pd.DataFrame, market: str, holdout: str) -> dict:
    spec = PROPS_MARKETS[market]
    feats, lines = spec["features"], spec["lines"]
    new = df[df.league == NEW_LEAGUE]
    test = new[new.season == holdout]
    cutoff = test.kickoff.min()
    train = df[df.league.isin(EXISTING + (NEW_LEAGUE,)) & (df.kickoff < cutoff)]
    hist = new[new.kickoff < cutoff]
    y = test["y"].to_numpy()
    ids = test["match_id"].to_numpy()

    m1, _ = fit(train, feats, lines)
    mu1 = predict_mu(m1, test, feats)
    m2, cals2, means = fit_offset(train, feats, lines)
    mu2 = predict_offset(m2, means, test, feats)
    # Sanity: the offset model must reproduce league levels on its own training rows.
    chk = predict_offset(m2, means, train, feats)

    own = float(hist["y"].mean())
    ll1, ll2 = ll_rows(y, mu1), ll_rows(y, mu2)
    ll_own = ll_rows(y, np.full(len(y), own))
    return {
        "holdout": holdout, "n_test": len(test), "n_train": len(train), "n_hist": len(hist),
        "means": means, "train_check": (float(chk.mean()), float(train["y"].mean())),
        "mean_actual": float(y.mean()), "mean_pred_m1": float(mu1.mean()),
        "mean_pred_m2": float(mu2.mean()), "own_mean": own,
        "ll_m1": float(ll1.mean()), "ll_m2": float(ll2.mean()), "ll_own": float(ll_own.mean()),
        "gain_m2_vs_own": boot_ci(ll_own - ll2, ids), "gain_m1_vs_own": boot_ci(ll_own - ll1, ids),
        "gain_m2_vs_m1": boot_ci(ll1 - ll2, ids),
        "calib": calibration(mu2, y, cals2, lines),
    }


def test_b(df: pd.DataFrame, market: str) -> dict:
    spec = PROPS_MARKETS[market]
    feats, lines = spec["features"], spec["lines"]
    cutoff = pd.Timestamp(B_CUTOFF, tz="UTC")
    base = df[df.league.isin(EXISTING) & (df.kickoff < cutoff)]
    extra = df[(df.league == NEW_LEAGUE) & (df.kickoff < cutoff)]
    test = df[df.league.isin(EXISTING) & (df.kickoff >= cutoff)]
    y = test["y"].to_numpy()
    ids = test["match_id"].to_numpy()
    m0, _ = fit(base, feats, lines)
    m2, _, means = fit_offset(pd.concat([base, extra], ignore_index=True), feats, lines)
    ll0 = ll_rows(y, predict_mu(m0, test, feats))
    ll2 = ll_rows(y, predict_offset(m2, means, test, feats))
    diff = ll2 - ll0  # positive = the offset model is worse than live
    res = {"n_base": len(base), "n_extra": len(extra), "n_test": len(test),
           "pooled": boot_ci(diff, ids), "by_league": {}}
    for lg in sorted(test.league.unique()):
        mask = (test.league == lg).to_numpy()
        res["by_league"][lg] = (int(mask.sum()),) + boot_ci(diff[mask], ids[mask])
    return res


def verdict(a1: dict, a2: dict, b: dict) -> dict:
    r1 = a1["gain_m2_vs_own"][1] > 0 and a2["gain_m2_vs_own"][0] > 0
    r2 = True
    for d in a1["calib"].values():
        if not d["cal_gap"] <= 0.05:
            r2 = False
        if any(n >= 100 and abs(a - s) > 0.07 for _, n, s, a in d["bands"]):
            r2 = False
    r3 = b["pooled"][2] < 0.001
    r4 = abs(a1["mean_pred_m2"] / a1["mean_actual"] - 1) <= 0.03
    return {"R1": r1, "R2": r2, "R3": r3, "R4": r4, "promote": all((r1, r2, r3, r4))}


def report(market: str, a1: dict, a2: dict, b: dict) -> None:
    ok = lambda v: "PASS" if v else "FAIL"  # noqa: E731
    print(f"\n===== league-level offset, {NEW_LEAGUE} {market} =====")
    print("league means used (2025-26 fit): " + ", ".join(f"{k} {v:.3f}" for k, v in a1["means"].items()))
    for a in (a1, a2):
        print(f"\nTest A, holdout {a['holdout']}: train {a['n_train']} rows (incl. {a['n_hist']} "
              f"{NEW_LEAGUE}), test {a['n_test']}")
        print(f"  sanity: M2 mean prediction on its own training rows {a['train_check'][0]:.3f} "
              f"vs mean actual {a['train_check'][1]:.3f}")
        print(f"  mean actual {a['mean_actual']:.3f} | M1 predicted {a['mean_pred_m1']:.3f} "
              f"({a['mean_pred_m1'] / a['mean_actual'] - 1:+.1%}) | M2 predicted {a['mean_pred_m2']:.3f} "
              f"({a['mean_pred_m2'] / a['mean_actual'] - 1:+.1%}) | own-history mean {a['own_mean']:.3f}")
        print(f"  Poisson log loss: M1 {a['ll_m1']:.4f}  M2 {a['ll_m2']:.4f}  own-mean {a['ll_own']:.4f}")
        for label, key in (("M2 vs own-mean", "gain_m2_vs_own"), ("M1 vs own-mean", "gain_m1_vs_own"),
                           ("M2 vs M1", "gain_m2_vs_m1")):
            g = a[key]
            print(f"  gain {label:15s} {g[0]:+.4f}  95% [{g[1]:+.4f}, {g[2]:+.4f}]")
    print(f"\nM2 calibration, holdout {a1['holdout']}:")
    for line, d in a1["calib"].items():
        print(f"  Over {line}: base rate {d['base_rate']:.3f}  calibrated quartile gap {d['cal_gap']:.3f}")
        for name, n, s, act in d["bands"]:
            flag = "  <-- >0.07" if n >= 100 and abs(act - s) > 0.07 else ""
            print(f"      band {name}: n={n:4d} stated {s:.3f} realized {act:.3f} gap {act - s:+.3f}{flag}")
    print(f"\nTest B: M2 (trained on {b['n_base']} existing + {b['n_extra']} {NEW_LEAGUE}) vs live M0, "
          f"{b['n_test']} existing-league rows since {B_CUTOFF}")
    m, lo, hi = b["pooled"]
    print(f"  log-loss change M2 minus M0 (positive = worse): {m:+.5f}  95% [{lo:+.5f}, {hi:+.5f}]")
    for lg, (n, m, lo, hi) in b["by_league"].items():
        print(f"    {lg:8s} n={n:5d} {m:+.5f}  [{lo:+.5f}, {hi:+.5f}]")
    v = verdict(a1, a2, b)
    print(f"\nVerdict: R1 skill {ok(v['R1'])} | R2 calibration {ok(v['R2'])} | R3 non-inferiority {ok(v['R3'])} "
          f"| R4 bias {ok(v['R4'])} -> {'PROMOTE' if v['promote'] else 'DO NOT PROMOTE'}")


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
