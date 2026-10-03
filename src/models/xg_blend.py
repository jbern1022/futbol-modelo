"""
Goals + xG blended Dixon-Coles (ADR-016).

XgRatings fits the same attack/defence parametrization as Dixon-Coles
(log lam = atk_h + dfn_a + gamma, log mu = atk_a + dfn_h) to xG instead of
goals, by weighted quasi-Poisson likelihood (y*log(rate) - rate; xG isn't
a count). BlendedDixonColes mixes the two on the log-rate scale,

    log rate = (1 - w) * log rate_goals + w * log rate_xg,

and keeps the goals fit's rho. It subclasses DixonColes and overrides only
rates(), so score_matrix()/predict() and every caller (slates, final pass,
live poller) work unchanged. A team the xG fit doesn't know (no xG rows in
the window) falls back to the goals rates.

Evidence: scripts/experiment_xg_blend.py and docs/EXPERIMENT_REGISTRY.md.
w = 0.5 was fixed before the La Liga test that promoted it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from dixon_coles import DixonColes

XG_BLEND_WEIGHT = 0.5
XG_BLEND_LEAGUES = frozenset({"EPL", "SERIE_A", "LA_LIGA"})


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

    def has(self, team: str) -> bool:
        return team in self.idx

    def log_rates(self, home: str, away: str) -> tuple[float, float]:
        n, p, i, j = len(self.teams), self.params, self.idx[home], self.idx[away]
        return float(p[i] + p[n + j] + p[2 * n]), float(p[j] + p[n + i])


class BlendedDixonColes(DixonColes):
    def __init__(self, goals: DixonColes, xg: XgRatings, weight: float = XG_BLEND_WEIGHT):
        super().__init__(xi=goals.xi)
        self.goals, self.xg, self.weight = goals, xg, weight
        self.teams, self.params, self._idx = goals.teams, goals.params, goals._idx

    @classmethod
    def fit(cls, df: pd.DataFrame, xi: float, reg: float,  # type: ignore[override]
            weight: float = XG_BLEND_WEIGHT) -> "BlendedDixonColes":
        goals = DixonColes(xi=xi).fit(df[["date", "home", "away", "hg", "ag"]], reg=reg)
        return cls(goals, XgRatings().fit(df, xi=xi, reg=reg), weight)

    def rates(self, home: str, away: str) -> tuple[float, float, float]:
        lam_g, mu_g, rho = self.goals.rates(home, away)
        if not (self.xg.has(home) and self.xg.has(away)):
            return lam_g, mu_g, rho
        llam_x, lmu_x = self.xg.log_rates(home, away)
        w = self.weight
        return (float(np.exp((1 - w) * np.log(lam_g) + w * llam_x)),
                float(np.exp((1 - w) * np.log(mu_g) + w * lmu_x)), rho)
