"""
Dixon-Coles match model (the "high-level" model).

Time-decayed bivariate Poisson with low-score dependency correction
(Dixon & Coles, 1997). Fits per-league. Outputs a full scoreline
distribution per fixture, from which all match-level markets derive:
1X2, total goals O/U, BTTS, clean sheets, exact scores.

Usage:
    model = DixonColes(xi=0.0018)          # xi = time decay per day
    model.fit(matches_df)                   # cols: date, home, away, hg, ag
    probs = model.predict("Inter", "Napoli")
    markets = derive_markets(probs)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

MAX_GOALS = 10  # scoreline grid size


def _tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Dixon-Coles low-score dependency adjustment."""
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


class DixonColes:
    def __init__(self, xi: float = 0.0018):
        """xi ~0.0018/day halves a match's weight in ~13 months."""
        self.xi = xi
        self.teams: list[str] = []
        self.params: np.ndarray | None = None

    # ---------- fitting ----------

    def fit(self, df: pd.DataFrame, reg: float = 0.0) -> "DixonColes":
        """
        df columns: date (datetime), home, away, hg, ag (ints).
        reg: L2 penalty on attack/defence parameters (ridge shrinkage
        toward the average team). Use reg=0 for a full club season with
        ~15-20 games/team. Use reg > 0 (try 5-15) for small, sparse
        samples like an in-progress international tournament, where the
        model can otherwise be underdetermined and unstable.
        """
        df = df.dropna(subset=["hg", "ag"]).copy()
        self.teams = sorted(set(df["home"]) | set(df["away"]))
        n = len(self.teams)
        idx = {t: i for i, t in enumerate(self.teams)}

        home_i = df["home"].map(idx).to_numpy()
        away_i = df["away"].map(idx).to_numpy()
        hg = df["hg"].to_numpy(int)
        ag = df["ag"].to_numpy(int)
        days_ago = (df["date"].max() - df["date"]).dt.days.to_numpy()
        w = np.exp(-self.xi * days_ago)

        # params: attack[n], defence[n], home_adv, rho
        x0 = np.concatenate([np.zeros(n), np.zeros(n), [0.25], [-0.05]])

        def nll(p: np.ndarray) -> float:
            atk, dfn = p[:n], p[n:2 * n]
            gamma, rho = p[2 * n], p[2 * n + 1]
            lam = np.exp(atk[home_i] + dfn[away_i] + gamma)   # home goal rate
            mu = np.exp(atk[away_i] + dfn[home_i])            # away goal rate
            tau = np.array([
                _tau(x, y, l, m, rho)
                for x, y, l, m in zip(hg, ag, lam, mu)
            ])
            tau = np.clip(tau, 1e-10, None)
            ll = w * (
                np.log(tau)
                + poisson.logpmf(hg, lam)
                + poisson.logpmf(ag, mu)
            )
            penalty = reg * (np.sum(atk ** 2) + np.sum(dfn ** 2)) if reg else 0.0
            return -ll.sum() + penalty

        # identifiability: mean attack = 0
        cons = [{"type": "eq", "fun": lambda p: p[:n].sum()}]
        res = minimize(nll, x0, constraints=cons, method="SLSQP",
                       options={"maxiter": 300, "ftol": 1e-8})
        self.params = res.x
        return self

    # ---------- inference ----------

    def rates(self, home: str, away: str) -> tuple[float, float, float]:
        n = len(self.teams)
        idx = {t: i for i, t in enumerate(self.teams)}
        p = self.params
        atk, dfn = p[:n], p[n:2 * n]
        gamma, rho = p[2 * n], p[2 * n + 1]
        lam = float(np.exp(atk[idx[home]] + dfn[idx[away]] + gamma))
        mu = float(np.exp(atk[idx[away]] + dfn[idx[home]]))
        return lam, mu, rho

    def score_matrix(self, home: str, away: str) -> np.ndarray:
        """P(home=i, away=j) grid, i,j in [0, MAX_GOALS]."""
        lam, mu, rho = self.rates(home, away)
        hp = poisson.pmf(np.arange(MAX_GOALS + 1), lam)
        ap = poisson.pmf(np.arange(MAX_GOALS + 1), mu)
        m = np.outer(hp, ap)
        for x in range(2):
            for y in range(2):
                m[x, y] *= _tau(x, y, lam, mu, rho)
        total = m.sum()
        if total < 1e-6:
            raise ValueError(
                f"score_matrix collapsed for {home} vs {away} "
                f"(lam={lam:.2f}, mu={mu:.2f}) — refit with reg>0."
            )
        return m / total

    def predict(self, home: str, away: str) -> dict:
        m = self.score_matrix(home, away)
        return {"matrix": m, "home": home, "away": away}


def derive_markets(pred: dict) -> dict:
    """All match-level markets from the scoreline distribution."""
    m = pred["matrix"]
    i, j = np.indices(m.shape)
    out = {
        "home_win": float(m[i > j].sum()),
        "draw": float(np.trace(m)),
        "away_win": float(m[i < j].sum()),
        "btts_yes": float(m[1:, 1:].sum()),
        "home_clean_sheet": float(m[:, 0].sum()),
        "away_clean_sheet": float(m[0, :].sum()),
    }
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        out[f"over_{line}"] = float(m[(i + j) > line].sum())
    # top 5 most likely exact scores
    flat = [((x, y), float(m[x, y])) for x in range(6) for y in range(6)]
    out["top_scorelines"] = sorted(flat, key=lambda t: -t[1])[:5]
    return out


def knockout_extension(match_probs: dict, et_scale: float = 0.31) -> dict:
    """
    For knockout fixtures (World Cup module): if draw after 90',
    extra time modeled as ~31% of a full match's goal expectation,
    then penalties as a coin flip with a tiny home/seed tilt.
    """
    draw_p = match_probs["draw"]
    # crude v1: split ET outcomes proportional to 90' win rates, pens 50/50
    hw, aw = match_probs["home_win"], match_probs["away_win"]
    ratio = hw / (hw + aw) if (hw + aw) > 0 else 0.5
    et_decisive = 0.55        # ~55% of ETs produce a winner (empirical)
    return {
        "advance_home": hw + draw_p * (et_decisive * ratio + (1 - et_decisive) * 0.5),
        "advance_away": aw + draw_p * (et_decisive * (1 - ratio) + (1 - et_decisive) * 0.5),
    }
