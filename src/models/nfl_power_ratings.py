"""
NFL match model -- power ratings via ridge regression, replacing
Dixon-Coles entirely for this sport (see the NFL-vs-NBA decision
record: NFL's scores cluster at 3/7-point increments, a multimodal
margin distribution Dixon-Coles' Poisson machinery was never built
for). Scope: SPREAD, MONEYLINE, TOTAL_POINTS only -- the scope-guarded
vertical slice, no player props.

Two independent ridge-regression fits on completed games:
  - margin rating: home_score - away_score ~ rating[home] - rating[away] + HFA
  - total rating:  home_score + away_score ~ level[home] + level[away] + intercept
    (a blended scoring-environment rating -- not a full offense/defense
    split; a fuller decomposition is real, separate future work)

Both are linear/Gaussian, not Poisson -- margin and total are
converted to probabilities via a Normal approximation using the
in-sample residual standard deviation. This is a real, known
simplification: NOT calibrated yet, unlike the soccer props models'
isotonic-on-out-of-fold-predictions treatment. There is no graded NFL
history to calibrate against before the season has actually been
played. Revisit once a real number of games have been graded -- same
pattern as the corners/SOT calibration fix, just not possible on day
one for a brand new sport.

Usage:
    model = NFLPowerRatings(alpha=5.0)
    model.fit(games_df)          # cols: home, away, home_score, away_score
    pred = model.predict("Kansas City Chiefs", "Buffalo Bills")
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm


class NFLPowerRatings:
    def __init__(self, alpha: float = 5.0):
        """alpha: ridge L2 penalty shrinking every team's rating toward
        the league average -- doubles as the identifiability constraint
        an unregularized fit would otherwise need (fixing one team's
        rating to zero), and tempers small-sample noise early in a
        season when few games have been played."""
        self.alpha = alpha
        self.teams: list[str] = []
        self.margin_ratings: dict[str, float] = {}
        self.home_field_advantage = 0.0
        self.sigma_margin = 13.5  # NFL's well-known rough margin SD; overwritten by fit()
        self.total_ratings: dict[str, float] = {}
        self.total_intercept = 0.0
        self.sigma_total = 10.0

    def fit(self, df: pd.DataFrame) -> "NFLPowerRatings":
        df = df.dropna(subset=["home_score", "away_score"]).copy()
        if df.empty:
            raise ValueError("no completed games to fit on")
        self.teams = sorted(set(df["home"]) | set(df["away"]))
        idx = {t: i for i, t in enumerate(self.teams)}
        n_teams = len(self.teams)
        n_games = len(df)

        # ---- margin model: rating[home] - rating[away] + HFA ----
        X = np.zeros((n_games, n_teams + 1))
        y_margin = np.zeros(n_games)
        for row_i, (_, g) in enumerate(df.iterrows()):
            X[row_i, idx[g["home"]]] = 1.0
            X[row_i, idx[g["away"]]] = -1.0
            X[row_i, n_teams] = 1.0  # HFA column
            y_margin[row_i] = g["home_score"] - g["away_score"]

        beta_margin = self._ridge_fit(X, y_margin)
        self.margin_ratings = {t: beta_margin[idx[t]] for t in self.teams}
        self.home_field_advantage = beta_margin[n_teams]
        resid = y_margin - X @ beta_margin
        self.sigma_margin = float(np.std(resid)) if n_games > n_teams else self.sigma_margin

        # ---- total model: level[home] + level[away] + intercept ----
        X_total = np.zeros((n_games, n_teams + 1))
        y_total = np.zeros(n_games)
        for row_i, (_, g) in enumerate(df.iterrows()):
            X_total[row_i, idx[g["home"]]] = 1.0
            X_total[row_i, idx[g["away"]]] = 1.0
            X_total[row_i, n_teams] = 1.0
            y_total[row_i] = g["home_score"] + g["away_score"]

        beta_total = self._ridge_fit(X_total, y_total)
        self.total_ratings = {t: beta_total[idx[t]] for t in self.teams}
        self.total_intercept = beta_total[n_teams]
        resid_total = y_total - X_total @ beta_total
        self.sigma_total = float(np.std(resid_total)) if n_games > n_teams else self.sigma_total

        return self

    def _ridge_fit(self, X: np.ndarray, y: np.ndarray) -> np.ndarray:
        n_cols = X.shape[1]
        penalty = self.alpha * np.eye(n_cols)
        penalty[-1, -1] = 0.0  # never shrink the intercept/HFA term itself
        return np.linalg.solve(X.T @ X + penalty, X.T @ y)

    def predict(self, home: str, away: str) -> dict:
        """Returns predicted_margin (home - away), predicted_total, and
        the two probability primitives every SPREAD/MONEYLINE/TOTAL_POINTS
        prediction is derived from -- prob_home_win and a total/margin
        Normal-CDF callable is left to the caller (generate_slate-style
        code) since the actual line (spread/total) isn't known here."""
        home_r = self.margin_ratings.get(home, 0.0)
        away_r = self.margin_ratings.get(away, 0.0)
        predicted_margin = home_r - away_r + self.home_field_advantage

        home_t = self.total_ratings.get(home, 0.0)
        away_t = self.total_ratings.get(away, 0.0)
        predicted_total = home_t + away_t + self.total_intercept

        return {
            "predicted_margin": predicted_margin,
            "sigma_margin": self.sigma_margin,
            "predicted_total": predicted_total,
            "sigma_total": self.sigma_total,
        }

    def prob_home_covers(self, home: str, away: str, line: float) -> float:
        """line: home team's spread in standard signed convention
        (negative = favored). Home covers iff margin > -line."""
        pred = self.predict(home, away)
        return float(1 - norm.cdf(-line, loc=pred["predicted_margin"], scale=pred["sigma_margin"]))

    def prob_home_wins(self, home: str, away: str) -> float:
        pred = self.predict(home, away)
        return float(1 - norm.cdf(0, loc=pred["predicted_margin"], scale=pred["sigma_margin"]))

    def prob_over(self, home: str, away: str, line: float) -> float:
        pred = self.predict(home, away)
        return float(1 - norm.cdf(line, loc=pred["predicted_total"], scale=pred["sigma_total"]))
