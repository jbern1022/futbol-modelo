"""
Does a small ridge penalty stop Dixon-Coles' early-season blowups?

Found 2026-10-02 (experiment_dynamic_ratings.py): in walk-forward,
production-settings Dixon-Coles (xi=0.0015, reg=0) gave one EPL and one
La Liga holdout match log loss 14.9 / 13.8 (~1-in-3-million for what
happened). Production hit the same thing live: degenerate_prediction_skips
logged EPL 1X2 at 5e-8 (Coventry win) and 6e-7 (Brentford at Hull) for
2026-27 promoted teams. A team with zero goals scored (or conceded) in
its whole fit window has an unbounded MLE rating with reg=0. ridge
(reg > 0) pulls every attack/defence toward the league average, which
barely moves teams with 100+ weighted matches and bounds the rest.

Same protocol as the other experiments: reg tuned on the season before
the holdout (weekly walk-forward, by mean log loss -- the tail is the
whole point), holdout scored once, paired against reg=0 with bootstrap
95% CIs on both RPS and log loss.

    python scripts/experiment_dc_ridge.py --league EPL --tune 2024-25 --holdout 2025-26
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import numpy as np
import pandas as pd
import psycopg2

from dixon_coles import DixonColes, derive_markets
from experiment_dynamic_ratings import DSN, PROD_XI, score
from train_dixon_coles import Q

REGS = (0.0, 0.25, 1.0, 4.0)


def dc_season(history: pd.DataFrame, season: pd.DataFrame, reg: float) -> dict:
    out, refit_at, model = {}, None, None
    for row in season.itertuples():
        if refit_at is None or row.date >= refit_at:
            past = pd.concat([history, season[season.date < row.date]])
            model = DixonColes(xi=PROD_XI).fit(past.assign(date=pd.to_datetime(past.date)), reg=reg)
            refit_at = row.date + timedelta(days=7)
        try:
            mk = derive_markets(model.predict(row.home, row.away))
        except (KeyError, ValueError):
            continue
        out[(row.date, row.home, row.away)] = [mk["home_win"], mk["draw"], mk["away_win"]]
    return out


def ci(diff: np.ndarray) -> tuple[float, float]:
    rng = np.random.default_rng(0)
    boots = [rng.choice(diff, len(diff)).mean() for _ in range(2000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(lo), float(hi)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["EPL", "SERIE_A", "LA_LIGA", "MLS"])
    ap.add_argument("--tune", required=True)
    ap.add_argument("--holdout", required=True)
    ap.add_argument("--fixed-reg", type=float, default=None,
                    help="skip tuning and score this reg on the holdout. The tune season can't "
                         "pick reg for a pathology it doesn't contain: 2024-25 had no blowups in "
                         "any league, so tuning by mean log loss chose reg=0 for 3 of 4.")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=(args.league,))
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    seasons = list(dict.fromkeys(df.season))
    ti, hi = seasons.index(args.tune), seasons.index(args.holdout)

    tune = df[df.season == args.tune]
    if args.fixed_reg is not None:
        best_reg = args.fixed_reg
    else:
        best_reg = None
    tune_hist = df[df.season.isin(seasons[:ti])]
    results = []
    for reg in (REGS if best_reg is None else ()):
        r, ll = score(dc_season(tune_hist, tune, reg), tune)
        results.append((float(ll.mean()), reg, float(r.mean()), float(ll.max())))
        print(f"{args.league} tune {args.tune} reg={reg:<5} RPS {r.mean():.4f}  "
              f"LL {ll.mean():.4f}  worst LL {ll.max():.2f}  n={len(r)}")
    if best_reg is None:
        best_reg = min(results)[1]

    hold = df[df.season == args.holdout]
    hist = df[df.season.isin(seasons[:hi])]
    base, cand = dc_season(hist, hold, 0.0), dc_season(hist, hold, best_reg)
    keys = set(base) & set(cand)
    r0, ll0 = score(base, hold, keys)
    r1, ll1 = score(cand, hold, keys)
    rlo, rhi = ci(r1 - r0)
    llo, lhi = ci(ll1 - ll0)
    print(f"{args.league} holdout {args.holdout}: reg={best_reg} vs reg=0 on {len(keys)} paired matches")
    print(f"   RPS {r0.mean():.4f} -> {r1.mean():.4f}  diff {(r1 - r0).mean():+.4f}  "
          f"95% CI [{rlo:+.4f}, {rhi:+.4f}]")
    print(f"   LL  {ll0.mean():.4f} -> {ll1.mean():.4f}  diff {(ll1 - ll0).mean():+.4f}  "
          f"95% CI [{llo:+.4f}, {lhi:+.4f}]")
    print(f"   worst LL {ll0.max():.2f} -> {ll1.max():.2f}; "
          f"min stated prob {min(min(v) for v in base.values()):.2e} -> {min(min(v) for v in cand.values()):.2e}")


if __name__ == "__main__":
    main()
