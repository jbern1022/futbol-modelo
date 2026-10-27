"""
Todoist 6hm4XP38mV4gGQ57: is the live corners/SOT over-confidence caused by
how the isotonic calibrators get their out-of-fold (OOF) predictions?

generate_slate.fit_props_model builds OOF predictions with a SHUFFLED
KFold(5). The features are rolling windows (corners_for_r5, ...), so a
held-out row's neighbours (same team, adjacent matches) share underlying
games with rows in the training folds. The OOF predictions are then sharper
than genuinely out-of-time ones, and the calibrator learns confidence the
model does not have live. src/models/props.py uses time-ordered folds
instead; the live path never did.

Holds the model fixed (one LightGBM fit on everything before the cutoff) and
changes only the calibrator's OOF scheme:
  shuffled  KFold(5, shuffle=True)         -- what is live today
  forward   expanding-window time folds    -- props.py's TimeSeriesSplit(5)
  blocked   5 contiguous time blocks, each scored by a model fit on the other
            four (no shuffling, so no adjacent-match leakage, but uses future)
Scored on matches at or after --cutoff (and before --until), with the live
emission rule (over p in 0.55..0.80, under p in 0.20..0.45 stated as 1-p).
Confidence intervals bootstrap by match: a fixture contributes several lines
and two teams, which are not independent.

Exploratory: the hypothesis came from reading the code, after the +8.7 pt
gap was observed. Not pre-registered. Read-only.

    python scripts/experiment_props_oof_scheme.py --market CORNERS --cutoff 2026-08-22
    python scripts/experiment_props_oof_scheme.py --market CORNERS --cutoff 2025-08-01 --until 2026-08-22
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import KFold, TimeSeriesSplit

from experiment_props_new_league import DSN, HYPERPARAMS, load
from generate_slate import PROPS_MARKETS, PROPS_OVER_BAND, PROPS_UNDER_BAND, lgb

SCHEMES = ("shuffled", "forward", "blocked")


def oof_mu(train: pd.DataFrame, feats: list[str], scheme: str) -> np.ndarray:
    """OOF expected counts for `train` (sorted by kickoff); NaN where a scheme has none."""
    X, y = train[feats], train["y"]
    out = np.full(len(train), np.nan)
    if scheme == "shuffled":
        folds = KFold(n_splits=5, shuffle=True, random_state=42).split(train)
    elif scheme == "forward":
        folds = TimeSeriesSplit(n_splits=5).split(train)
    else:
        folds = KFold(n_splits=5, shuffle=False).split(train)
    for tr, va in folds:
        m = lgb.LGBMRegressor(verbose=-1, **HYPERPARAMS).fit(X.iloc[tr], y.iloc[tr])
        out[va] = np.maximum(m.predict(X.iloc[va]), 0.05)
    return out


def calibrators(oof: np.ndarray, y: np.ndarray, lines: list[float]) -> dict:
    ok = ~np.isnan(oof)
    cals = {}
    for line in lines:
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
        iso.fit(1 - poisson.cdf(np.floor(line), oof[ok]), (y[ok] > line).astype(int))
        cals[line] = iso
    return cals


def emitted(test: pd.DataFrame, mu: np.ndarray, cals: dict, lines: list[float]) -> pd.DataFrame:
    rows = []
    for line in lines:
        p = cals[line].predict(1 - poisson.cdf(np.floor(line), mu))
        over = (p >= PROPS_OVER_BAND[0]) & (p <= PROPS_OVER_BAND[1])
        under = (p >= PROPS_UNDER_BAND[0]) & (p <= PROPS_UNDER_BAND[1])
        hit_over = (test["y"].values > line)
        for mask, side in ((over, "over"), (under, "under")):
            stated = p[mask] if side == "over" else 1 - p[mask]
            hit = hit_over[mask] if side == "over" else ~hit_over[mask]
            rows.append(pd.DataFrame({"match_id": test["match_id"].values[mask], "league": test["league"].values[mask],
                                      "line": line, "side": side, "p": stated, "hit": hit.astype(int)}))
    return pd.concat(rows, ignore_index=True)


def gap_ci(g: pd.DataFrame, seed: int = 0, n_boot: int = 1000) -> tuple[float, float, float]:
    """Realized minus stated, with a bootstrap-by-match 95% CI."""
    rng = np.random.default_rng(seed)
    ids = g["match_id"].values
    uniq, inv = np.unique(ids, return_inverse=True)
    by_match = [np.where(inv == i)[0] for i in range(len(uniq))]
    h, p = g["hit"].values, g["p"].values
    gaps = []
    for _ in range(n_boot):
        s = np.concatenate([by_match[i] for i in rng.integers(0, len(uniq), len(uniq))])
        gaps.append(h[s].mean() - p[s].mean())
    return h.mean() - p.mean(), *np.percentile(gaps, [2.5, 97.5])


def line(label: str, g: pd.DataFrame) -> str:
    if len(g) < 30:
        return f"    {label:22s}n={len(g):5d}  (too few to report)"
    gap, lo, hi = gap_ci(g)
    return (f"    {label:22s}n={len(g):5d} stated={g['p'].mean():.3f} real={g['hit'].mean():.3f} "
            f"gap={gap:+.3f} [{lo:+.3f},{hi:+.3f}]")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["CORNERS", "SOT"])
    ap.add_argument("--cutoff", required=True, help="train strictly before, score at or after (UTC date)")
    ap.add_argument("--until", help="score strictly before this date (default: no limit)")
    args = ap.parse_args()
    spec = PROPS_MARKETS[args.market]
    feats, lines = spec["features"], spec["lines"]
    with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
        df = load(cur, args.market, tuple(sorted(spec["leagues"])))
    df = df.sort_values(["kickoff", "match_id"]).reset_index(drop=True)
    cut = pd.Timestamp(args.cutoff, tz="UTC")
    train = df[df["kickoff"] < cut].reset_index(drop=True)
    test = df[df["kickoff"] >= cut]
    if args.until:
        test = test[test["kickoff"] < pd.Timestamp(args.until, tz="UTC")]
    test = test.reset_index(drop=True)
    print(f"{args.market}: train {len(train)} team-matches before {args.cutoff}; "
          f"score {len(test)} team-matches ({test['match_id'].nunique()} fixtures)")
    model = lgb.LGBMRegressor(verbose=-1, **HYPERPARAMS).fit(train[feats], train["y"])
    mu = np.maximum(model.predict(test[feats]), 0.05)
    print(f"  mean predicted {mu.mean():.3f} vs realized {test['y'].mean():.3f}")
    for scheme in SCHEMES:
        oof = oof_mu(train, feats, scheme)
        ok = ~np.isnan(oof)
        mae = np.abs(oof[ok] - train["y"].values[ok]).mean()
        em = emitted(test, mu, calibrators(oof, train["y"].values, lines), lines)
        print(f"\n  [{scheme}] OOF MAE {mae:.4f} on {ok.sum()} rows; emitted {len(em)} candidates")
        print(line("all emitted", em))
        for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.75), (0.75, 0.801)):
            print(line(f"band {lo:.2f}-{min(hi, 0.8):.2f}", em[(em["p"] >= lo) & (em["p"] < hi)]))
        print(line("0.70+ over", em[(em["p"] >= 0.7) & (em["side"] == "over")]))
        print(line("0.70+ under", em[(em["p"] >= 0.7) & (em["side"] == "under")]))


if __name__ == "__main__":
    main()
