"""
Todoist 6hf54hvcpV9p7Vff: benchmark dynamic attack/defence ratings
against the current Dixon-Coles 1X2 model.

Baseline (production settings, scripts/generate_slate.py
fit_dixon_coles): Dixon-Coles, xi=0.0015 time decay, reg=0, refit
weekly through the season (production refits daily; weekly is what
scripts/train_dixon_coles.py's walk-forward already uses).

Candidate: a score-driven rating model on the SAME parametrization
(log lam = atk_h + dfn_a + gamma, log mu = atk_a + dfn_h). Ratings
start each season from a Dixon-Coles fit on everything before it,
shrunk toward the league average by `shrink`; then after every match
the Poisson log-likelihood gradient moves them:
    atk_h, dfn_a += eta * (home_goals - lam)
    atk_a, dfn_h += eta * (away_goals - mu)
gamma and rho stay at the season-start fit. Promoted teams (no prior
history) start at the bottom-quintile attack / top-quintile defence
rating (defence here = goals conceded, higher is worse).

Protocol (docs/RESEARCH_PROTOCOL.md): eta and shrink are tuned on the
season BEFORE the holdout; the holdout is scored once with the chosen
values. Comparison is paired -- only matches both models predict
(Dixon-Coles can't price a promoted team until it has played) --
with a bootstrap 95% CI on the mean RPS difference.

    python scripts/experiment_dynamic_ratings.py --league EPL --tune 2024-25 --holdout 2025-26
    python scripts/experiment_dynamic_ratings.py --league MLS --tune 2024 --holdout 2025
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson

from dixon_coles import DixonColes, derive_markets
from dixon_coles._model import MAX_GOALS, _tau
from train_dixon_coles import Q, rps

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
PROD_XI = 0.0015
ETAS = (0.01, 0.02, 0.03, 0.05, 0.08)
SHRINKS = (1.0, 0.8, 0.6)


def probs_from_rates(lam: float, mu: float, rho: float) -> list[float]:
    hp = poisson.pmf(np.arange(MAX_GOALS + 1), lam)
    ap = poisson.pmf(np.arange(MAX_GOALS + 1), mu)
    m = np.outer(hp, ap)
    for x in range(2):
        for y in range(2):
            m[x, y] *= _tau(x, y, lam, mu, rho)
    m = np.clip(m, 0, None)
    m /= m.sum()
    i, j = np.indices(m.shape)
    return [float(m[i > j].sum()), float(np.trace(m)), float(m[i < j].sum())]


def fit_dc(past: pd.DataFrame) -> DixonColes:
    return DixonColes(xi=PROD_XI).fit(past.assign(date=pd.to_datetime(past.date)))


def outcome(row) -> int:
    return 0 if row.hg > row.ag else (1 if row.hg == row.ag else 2)


def dynamic_season(start_fit: DixonColes, season: pd.DataFrame, eta: float, shrink: float) -> dict:
    """Per-match 1X2 probabilities from the score-driven model, keyed by
    (date, home, away). Each match is predicted BEFORE its own update."""
    n = len(start_fit.teams)
    p = start_fit.params
    atk0, dfn0 = p[:n], p[n:2 * n]
    gamma, rho = p[2 * n], p[2 * n + 1]
    dfn_mean = dfn0.mean()
    atk = {t: shrink * atk0[i] for i, t in enumerate(start_fit.teams)}
    dfn = {t: dfn_mean + shrink * (dfn0[i] - dfn_mean) for i, t in enumerate(start_fit.teams)}
    new_atk, new_dfn = float(np.quantile(atk0, 0.2)), float(np.quantile(dfn0, 0.8))

    out = {}
    for row in season.itertuples():
        for t in (row.home, row.away):
            atk.setdefault(t, new_atk)
            dfn.setdefault(t, new_dfn)
        lam = float(np.exp(atk[row.home] + dfn[row.away] + gamma))
        mu = float(np.exp(atk[row.away] + dfn[row.home]))
        out[(row.date, row.home, row.away)] = probs_from_rates(lam, mu, rho)
        e_h, e_a = row.hg - lam, row.ag - mu
        atk[row.home] += eta * e_h
        dfn[row.away] += eta * e_h
        atk[row.away] += eta * e_a
        dfn[row.home] += eta * e_a
    return out


def dc_season(history: pd.DataFrame, season: pd.DataFrame) -> dict:
    """Weekly-refit Dixon-Coles walk-forward, same as train_dixon_coles."""
    out, refit_at, model = {}, None, None
    for row in season.itertuples():
        if refit_at is None or row.date >= refit_at:
            model = fit_dc(pd.concat([history, season[season.date < row.date]]))
            refit_at = row.date + timedelta(days=7)
        try:
            mk = derive_markets(model.predict(row.home, row.away))
        except KeyError:
            continue
        out[(row.date, row.home, row.away)] = [mk["home_win"], mk["draw"], mk["away_win"]]
    return out


def score(preds: dict, season: pd.DataFrame, keys=None) -> tuple[np.ndarray, np.ndarray]:
    r, ll = [], []
    for row in season.itertuples():
        k = (row.date, row.home, row.away)
        if k not in preds or (keys is not None and k not in keys):
            continue
        p, a = preds[k], outcome(row)
        r.append(rps(p, a))
        ll.append(-np.log(max(p[a], 1e-9)))
    return np.array(r), np.array(ll)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["EPL", "SERIE_A", "LA_LIGA", "MLS"])
    ap.add_argument("--tune", required=True)
    ap.add_argument("--holdout", required=True)
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=(args.league,))
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    seasons = list(dict.fromkeys(df.season))
    ti, hi = seasons.index(args.tune), seasons.index(args.holdout)
    assert ti < hi, "tune season must come before the holdout"

    # --- tune on the season before the holdout -----------------------
    tune = df[df.season == args.tune]
    tune_fit = fit_dc(df[df.season.isin(seasons[:ti])])
    grid = []
    for eta, shrink in itertools.product(ETAS, SHRINKS):
        r, _ = score(dynamic_season(tune_fit, tune, eta, shrink), tune)
        grid.append((float(r.mean()), eta, shrink))
    grid.sort()
    _, eta, shrink = grid[0]
    print(f"{args.league}: tuned on {args.tune} ({len(tune)} matches) -> eta={eta}, shrink={shrink}")
    for g in grid[:3]:
        print(f"   tune RPS {g[0]:.4f}  eta={g[1]}  shrink={g[2]}")

    # --- score the holdout once --------------------------------------
    hold = df[df.season == args.holdout]
    history = df[df.season.isin(seasons[:hi])]
    dyn = dynamic_season(fit_dc(history), hold, eta, shrink)
    dc = dc_season(history, hold)
    paired = set(dyn) & set(dc)
    r_dyn, ll_dyn = score(dyn, hold, paired)
    r_dc, ll_dc = score(dc, hold, paired)
    diff = r_dyn - r_dc
    rng = np.random.default_rng(0)
    boots = [rng.choice(diff, len(diff)).mean() for _ in range(2000)]
    lo, hi_ci = np.percentile(boots, [2.5, 97.5])
    print(f"holdout {args.holdout}: {len(paired)} paired matches "
          f"(dynamic-only: {len(set(dyn) - paired)})")
    print(f"   RPS      Dixon-Coles {r_dc.mean():.4f}  dynamic {r_dyn.mean():.4f}  "
          f"diff {diff.mean():+.4f}  95% CI [{lo:+.4f}, {hi_ci:+.4f}]")
    ll_diff = ll_dyn - ll_dc
    ll_boots = [rng.choice(ll_diff, len(ll_diff)).mean() for _ in range(2000)]
    ll_lo, ll_hi = np.percentile(ll_boots, [2.5, 97.5])
    print(f"   log loss Dixon-Coles {ll_dc.mean():.4f}  dynamic {ll_dyn.mean():.4f}  "
          f"diff {ll_diff.mean():+.4f}  95% CI [{ll_lo:+.4f}, {ll_hi:+.4f}]")
    worst = np.argsort(ll_dc)[-3:][::-1]
    print("   Dixon-Coles' 3 worst log-loss matches (dc LL vs dynamic LL): "
          + ", ".join(f"{ll_dc[i]:.2f} vs {ll_dyn[i]:.2f}" for i in worst))
    verdict = ("dynamic better" if hi_ci < 0 else "Dixon-Coles better" if lo > 0
               else "no significant difference")
    print(f"   verdict: {verdict} (negative diff = dynamic has lower RPS)")


if __name__ == "__main__":
    main()
