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


class UnratedTeamError(KeyError):
    """Raised when predicting for a team absent from the fit with no prior set."""


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
        # Ratings applied to a team with no match history in this league —
        # newly promoted sides. Without this every fixture involving one is
        # unratable, and the slate generator skipped them outright: in one
        # real run that was 9 of 13 upcoming Premier League fixtures.
        self.prior_attack: float | None = None
        self.prior_defence: float | None = None

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

        def tau_margin(p: np.ndarray) -> float:
            """
            Smallest low-score correction across the training set.

            The Dixon-Coles tau adjustment is only a valid probability
            adjustment while all four of its cases stay positive, which bounds
            rho relative to the scoring rates. Without this the optimiser is
            free to pick a rho that makes tau negative: the clip inside nll()
            hides it during fitting, and score_matrix() then applies the same
            rho unclipped and produces negative probabilities.
            """
            atk, dfn = p[:n], p[n:2 * n]
            gamma, rho = p[2 * n], p[2 * n + 1]
            lam = np.exp(atk[home_i] + dfn[away_i] + gamma)
            mu = np.exp(atk[away_i] + dfn[home_i])
            return float(np.min(np.concatenate([
                1 - lam * mu * rho,
                1 + lam * rho,
                1 + mu * rho,
                np.array([1 - rho]),
            ])) - 1e-4)

        # identifiability: mean attack = 0
        cons = [
            {"type": "eq", "fun": lambda p: p[:n].sum()},
            {"type": "ineq", "fun": tau_margin},
        ]
        res = minimize(nll, x0, constraints=cons, method="SLSQP",
                       options={"maxiter": 300, "ftol": 1e-8})
        self.params = res.x
        return self

    # ---------- inference ----------

    def knows(self, team: str) -> bool:
        return team in self.teams

    def set_unknown_team_prior(self, attack: float, defence: float) -> None:
        """
        Ratings to use for a team absent from the fit — in practice a newly
        promoted side with no top-flight history.

        Callers should derive these from data (see promoted_team_prior in
        scripts/generate_slate.py, which measures how previously promoted
        teams actually performed) rather than inventing a number.
        """
        self.prior_attack = float(attack)
        self.prior_defence = float(defence)

    def _team_params(self, team: str, atk: np.ndarray, dfn: np.ndarray,
                     idx: dict[str, int]) -> tuple[float, float]:
        if team in idx:
            return float(atk[idx[team]]), float(dfn[idx[team]])
        if self.prior_attack is None or self.prior_defence is None:
            raise UnratedTeamError(
                f"{team!r} has no match history in this fit and no prior is "
                f"set. Call set_unknown_team_prior() before predicting for "
                f"promoted or newly added teams."
            )
        return self.prior_attack, self.prior_defence

    def rates(self, home: str, away: str) -> tuple[float, float, float]:
        n = len(self.teams)
        idx = {t: i for i, t in enumerate(self.teams)}
        p = self.params
        atk, dfn = p[:n], p[n:2 * n]
        gamma, rho = p[2 * n], p[2 * n + 1]
        atk_h, dfn_h = self._team_params(home, atk, dfn, idx)
        atk_a, dfn_a = self._team_params(away, atk, dfn, idx)
        lam = float(np.exp(atk_h + dfn_a + gamma))
        mu = float(np.exp(atk_a + dfn_h))
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

        # tau can still drive a cell negative for rates outside the range the
        # fit was constrained over — an unrated team using a prior, say. A
        # negative cell is not a probability, so clip it, but refuse to
        # normalise away a meaningful amount of mass: that would silently
        # return a confident-looking distribution the model does not support.
        negative_mass = float(-m[m < 0].sum()) if (m < 0).any() else 0.0
        if negative_mass > 0:
            m = np.clip(m, 0.0, None)
            if negative_mass > 0.01 * m.sum():
                raise ValueError(
                    f"score_matrix invalid for {home} vs {away} "
                    f"(lam={lam:.2f}, mu={mu:.2f}, rho={rho:.3f}): the "
                    f"low-score correction went negative by "
                    f"{negative_mass:.3g}. Refit, or widen the prior."
                )
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
