"""
Todoist 6hf57MFQwFpGmp57: does blending xG into the Dixon-Coles 1X2 fit
beat goals alone?

Two fits on the same parametrization (log lam = atk_h + dfn_a + gamma,
log mu = atk_a + dfn_h), both with production weighting (xi=0.0015,
ridge reg=0.25, ADR-014):
  goals  -- production Dixon-Coles (scores, with rho)
  xG     -- the same ratings fit to Understat xG by quasi-Poisson
            likelihood (y*log(rate) - rate; xG isn't a count), no rho
Blend: log rate = (1 - w) * log rate_goals + w * log rate_xg, with the
goals model's rho. w = 0 is production.

Protocol: w tuned on the season before the holdout (weekly walk-forward,
by RPS), holdout scored once, paired against w = 0 with bootstrap 95%
CIs. EPL and SERIE_A only -- the leagues with Understat xG for every
season (La Liga has 2025-26 only, MLS none).

    python scripts/experiment_xg_blend.py --league EPL --tune 2024-25 --holdout 2025-26
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

WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)

Q = """
SELECT m.kickoff_utc::date AS date, th.name AS home, ta.name AS away,
       m.home_score AS hg, m.away_score AS ag, se.label AS season,
       h.xg AS hxg, a.xg AS axg
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


class XgRatings:
    """Attack/defence ratings fit to xG by weighted quasi-Poisson likelihood."""

    def fit(self, df: pd.DataFrame, xi: float, reg: float) -> "XgRatings":
        df = df.dropna(subset=["hxg", "axg"])
        self.teams = sorted(set(df.home) | set(df.away))
        n = len(self.teams)
        self.idx = {t: i for i, t in enumerate(self.teams)}
        hi = df.home.map(self.idx).to_numpy()
        ai = df.away.map(self.idx).to_numpy()
        hx, ax = df.hxg.to_numpy(float), df.axg.to_numpy(float)
        w = np.exp(-xi * (df.date.max() - df.date).dt.days.to_numpy())

        def nll_and_grad(p):
            atk, dfn, g = p[:n], p[n:2 * n], p[2 * n]
            lh = atk[hi] + dfn[ai] + g
            la = atk[ai] + dfn[hi]
            eh, ea = np.exp(lh), np.exp(la)
            nll = -np.sum(w * (hx * lh - eh + ax * la - ea)) + reg * (atk @ atk + dfn @ dfn)
            rh, ra = w * (hx - eh), w * (ax - ea)   # d ll / d log-rate
            grad = np.zeros_like(p)
            np.add.at(grad, hi, -rh)
            np.add.at(grad, n + ai, -rh)
            np.add.at(grad, ai, -ra)
            np.add.at(grad, n + hi, -ra)
            grad[2 * n] = -rh.sum()
            grad[:n] += 2 * reg * atk
            grad[n:2 * n] += 2 * reg * dfn
            return nll, grad

        res = minimize(nll_and_grad, np.r_[np.zeros(2 * n), 0.25], jac=True, method="L-BFGS-B")
        self.params = res.x
        return self

    def log_rates(self, home: str, away: str) -> tuple[float, float]:
        n, p, i, j = len(self.teams), self.params, self.idx[home], self.idx[away]
        return p[i] + p[n + j] + p[2 * n], p[j] + p[n + i]


def season_preds(history: pd.DataFrame, season: pd.DataFrame) -> dict:
    """Weekly-refit walk-forward; per match, 1X2 for every blend weight."""
    out, refit_at = {}, None
    for row in season.itertuples():
        if refit_at is None or row.date >= refit_at:
            past = pd.concat([history, season[season.date < row.date]])
            xi, reg = dc_fit_settings(len(past))
            goals = DixonColes(xi=xi).fit(past[["date", "home", "away", "hg", "ag"]], reg=reg)
            xgm = XgRatings().fit(past, xi, reg)
            refit_at = row.date + timedelta(days=7)
        try:
            lam_g, mu_g, rho = goals.rates(row.home, row.away)
            llam_x, lmu_x = xgm.log_rates(row.home, row.away)
        except KeyError:
            continue
        out[(row.date, row.home, row.away)] = {
            w: probs_from_rates(float(np.exp((1 - w) * np.log(lam_g) + w * llam_x)),
                                float(np.exp((1 - w) * np.log(mu_g) + w * lmu_x)), rho)
            for w in WEIGHTS}
    return out


def scores(preds: dict, season: pd.DataFrame, w: float) -> tuple[np.ndarray, np.ndarray]:
    from train_dixon_coles import rps
    r, ll = [], []
    for row in season.itertuples():
        k = (row.date, row.home, row.away)
        if k not in preds:
            continue
        p = preds[k][w]
        a = 0 if row.hg > row.ag else (1 if row.hg == row.ag else 2)
        r.append(rps(p, a))
        ll.append(-np.log(max(p[a], 1e-9)))
    return np.array(r), np.array(ll)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["EPL", "SERIE_A"])
    ap.add_argument("--tune", required=True)
    ap.add_argument("--holdout", required=True)
    ap.add_argument("--dump", help="write per-match (rps_goals, rps_blend, ll_goals, ll_blend) to this .npy, "
                                   "for pooling rolling-origin holdouts")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=(args.league,))
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    seasons = list(dict.fromkeys(df.season))
    ti, hi = seasons.index(args.tune), seasons.index(args.holdout)

    tune = df[df.season == args.tune]
    tune_preds = season_preds(df[df.season.isin(seasons[:ti])], tune)
    tuned = []
    for w in WEIGHTS:
        r, ll = scores(tune_preds, tune, w)
        tuned.append((float(r.mean()), w))
        print(f"{args.league} tune {args.tune} w={w:<4} RPS {r.mean():.4f}  LL {ll.mean():.4f}  n={len(r)}")
    best_w = min(tuned)[1]

    hold = df[df.season == args.holdout]
    preds = season_preds(df[df.season.isin(seasons[:hi])], hold)
    r0, ll0 = scores(preds, hold, 0.0)
    r1, ll1 = scores(preds, hold, best_w)
    if args.dump:
        np.save(args.dump, np.c_[r0, r1, ll0, ll1])
    rlo, rhi = ci(r1 - r0)
    llo, lhi = ci(ll1 - ll0)
    print(f"{args.league} holdout {args.holdout}: w={best_w} vs goals-only, {len(r0)} matches")
    print(f"   RPS {r0.mean():.4f} -> {r1.mean():.4f}  diff {(r1 - r0).mean():+.4f}  "
          f"95% CI [{rlo:+.4f}, {rhi:+.4f}]")
    print(f"   LL  {ll0.mean():.4f} -> {ll1.mean():.4f}  diff {(ll1 - ll0).mean():+.4f}  "
          f"95% CI [{llo:+.4f}, {lhi:+.4f}]")
    for w in WEIGHTS:
        r, ll = scores(preds, hold, w)
        print(f"   (holdout, for reference only) w={w:<4} RPS {r.mean():.4f}  LL {ll.mean():.4f}")


if __name__ == "__main__":
    main()
