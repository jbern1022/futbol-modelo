"""
Todoist 6hf54j2hMP87xjR7: do rest and fixture congestion move goal rates?

Rest is measured across ALL competitions (futbol.team_fixtures, migration
0042: league, domestic cups, continental; friendlies excluded), so a team
coming off a Thursday European tie is correctly tired on Sunday.

Baseline: production-settings rates (xi/reg from dc_fit_settings, 50/50
goals+xG blend for EPL/SERIE_A/LA_LIGA per ADR-016, goals-only for MLS),
refit weekly through each season -- the same walk-forward as every other
experiment here.

Adjustment, per goal rate (home goals use lam, away goals use mu):
    log rate' = log rate + b1*short_rest_own + b2*short_rest_opp + b3*congestion_diff
  short_rest = 1 if <= 3 days since the team's previous competitive match
  congestion_diff = clip(own matches in prior 14 days - opponent's, -3, 3)
Fit by ridge-penalized Poisson likelihood with the baseline as an offset,
on the --train seasons' walk-forward rates; scored once on --holdout,
paired against the unadjusted baseline (bootstrap 95% CIs). No home-
advantage term: the baseline already has one, so it isn't counted twice.

    python scripts/experiment_rest_congestion.py --league EPL --train 2023-24 2024-25 --holdout 2025-26
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.optimize import minimize

from dixon_coles import DixonColes
from experiment_dc_ridge import ci
from experiment_dynamic_ratings import DSN, probs_from_rates
from models.dc_settings import dc_fit_settings
from models.xg_blend import XG_BLEND_LEAGUES, BlendedDixonColes
from train_dixon_coles import rps

RIDGE = 1.0

Q = """
SELECT m.kickoff_utc, m.kickoff_utc::date AS date, th.name AS home, ta.name AS away,
       m.home_team_id, m.away_team_id, m.home_score AS hg, m.away_score AS ag,
       se.label AS season, h.xg AS hxg, a.xg AS axg
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons se ON se.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = se.league_id
LEFT JOIN futbol.team_match_stats h ON h.match_id = m.match_id AND h.team_id = m.home_team_id
LEFT JOIN futbol.team_match_stats a ON a.match_id = m.match_id AND a.team_id = m.away_team_id
WHERE l.code = %s AND m.status = 'final'
ORDER BY m.kickoff_utc
"""

FIXTURES_Q = """
SELECT team_id, kickoff_utc FROM futbol.team_fixtures
WHERE status_short IN ('FT', 'AET', 'PEN') ORDER BY team_id, kickoff_utc
"""


def fatigue(fixtures: dict, team_id: int, kickoff) -> tuple[float, float] | None:
    """(days since previous competitive match, matches in prior 14 days),
    or None if this team-season has no fixture coverage."""
    ks = fixtures.get(team_id)
    if ks is None:
        return None
    prior = ks[ks < kickoff - pd.Timedelta(hours=2)]
    if len(prior) == 0:
        return None
    rest = (kickoff - prior[-1]).total_seconds() / 86400
    n14 = int((prior >= kickoff - pd.Timedelta(days=14)).sum())
    return rest, n14


def baseline_rates(df: pd.DataFrame, league: str, season: str) -> dict:
    hist, cur = df[df.season < season], df[df.season == season]
    out, refit_at, model = {}, None, None
    for row in cur.itertuples():
        if refit_at is None or row.date >= refit_at:
            past = pd.concat([hist, cur[cur.date < row.date]])
            xi, reg = dc_fit_settings(len(past))
            if league in XG_BLEND_LEAGUES and past.hxg.notna().any():
                model = BlendedDixonColes.fit(past, xi=xi, reg=reg)
            else:
                model = DixonColes(xi=xi).fit(past[["date", "home", "away", "hg", "ag"]], reg=reg)
            refit_at = row.date + timedelta(days=7)
        try:
            out[row.Index] = model.rates(row.home, row.away)
        except KeyError:
            continue
    return out


def design(df: pd.DataFrame, rates: dict, fixtures: dict) -> pd.DataFrame:
    rows = []
    for idx, (lam, mu, rho) in rates.items():
        r = df.loc[idx]
        fh = fatigue(fixtures, r.home_team_id, r.kickoff_utc)
        fa = fatigue(fixtures, r.away_team_id, r.kickoff_utc)
        if fh is None or fa is None:
            continue
        sh, sa = float(fh[0] <= 3), float(fa[0] <= 3)
        cd = float(np.clip(fh[1] - fa[1], -3, 3))
        rows.append({"idx": idx, "lam": lam, "mu": mu, "rho": rho, "hg": r.hg, "ag": r.ag,
                     "xh": (sh, sa, cd), "xa": (sa, sh, -cd)})
    return pd.DataFrame(rows)


def fit_adjustment(d: pd.DataFrame) -> np.ndarray:
    X = np.array(list(d.xh) + list(d.xa))
    y = np.r_[d.hg.to_numpy(float), d.ag.to_numpy(float)]
    off = np.log(np.r_[d.lam.to_numpy(), d.mu.to_numpy()])

    def nll(b):
        eta = off + X @ b
        return -(y @ eta - np.exp(eta).sum()) + RIDGE * b @ b, -(X.T @ (y - np.exp(eta))) + 2 * RIDGE * b

    return minimize(nll, np.zeros(3), jac=True, method="L-BFGS-B").x


def score(d: pd.DataFrame, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    r0, r1, l0, l1 = [], [], [], []
    for row in d.itertuples():
        a = 0 if row.hg > row.ag else (1 if row.hg == row.ag else 2)
        p0 = probs_from_rates(row.lam, row.mu, row.rho)
        p1 = probs_from_rates(row.lam * np.exp(np.dot(row.xh, b)), row.mu * np.exp(np.dot(row.xa, b)), row.rho)
        r0.append(rps(p0, a))
        r1.append(rps(p1, a))
        l0.append(-np.log(max(p0[a], 1e-9)))
        l1.append(-np.log(max(p1[a], 1e-9)))
    return np.array(r0), np.array(r1), np.array(l0), np.array(l1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["EPL", "SERIE_A", "LA_LIGA", "MLS"])
    ap.add_argument("--train", nargs="+", required=True)
    ap.add_argument("--holdout", required=True)
    ap.add_argument("--dump", help="write per-match (rps0, rps1, ll0, ll1) .npy for pooling")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=(args.league,))
    fx = pd.read_sql(FIXTURES_Q, conn)
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    df["kickoff_utc"] = pd.to_datetime(df["kickoff_utc"], utc=True)
    df[["hxg", "axg"]] = df[["hxg", "axg"]].apply(pd.to_numeric, errors="coerce")
    fx["kickoff_utc"] = pd.to_datetime(fx["kickoff_utc"], utc=True)
    fixtures = {t: g.kickoff_utc.to_numpy() for t, g in fx.groupby("team_id")}
    fixtures = {t: pd.DatetimeIndex(v) for t, v in fixtures.items()}

    train = pd.concat([design(df, baseline_rates(df, args.league, s), fixtures) for s in args.train])
    b = fit_adjustment(train)
    print(f"{args.league}: fit on {len(train)} matches ({', '.join(args.train)})")
    print(f"   coefficients: short_rest_own {b[0]:+.3f}  short_rest_opp {b[1]:+.3f}  "
          f"congestion_diff {b[2]:+.3f}   (log-rate; e.g. {b[0]:+.3f} = {np.exp(b[0]) - 1:+.1%} goals)")
    print(f"   train share short rest: {np.mean([x[0] for x in train.xh]):.1%} of team-matches")

    hold = design(df, baseline_rates(df, args.league, args.holdout), fixtures)
    r0, r1, l0, l1 = score(hold, b)
    if args.dump:
        np.save(args.dump, np.c_[r0, r1, l0, l1])
    rlo, rhi = ci(r1 - r0)
    llo, lhi = ci(l1 - l0)
    print(f"   holdout {args.holdout} ({len(hold)} matches): RPS {r0.mean():.4f} -> {r1.mean():.4f}  "
          f"diff {(r1 - r0).mean():+.4f}  95% CI [{rlo:+.4f}, {rhi:+.4f}]")
    print(f"   LL {l0.mean():.4f} -> {l1.mean():.4f}  diff {(l1 - l0).mean():+.4f}  95% CI [{llo:+.4f}, {lhi:+.4f}]")


if __name__ == "__main__":
    main()
