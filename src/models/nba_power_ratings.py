"""
NBA match model -- total-points-only power ratings via ridge regression.
Scope: TOTAL_POINTS only (see the NBA scope-guard ticket -- totals +
player points props, no moneyline/spread for this vertical slice), so
unlike nfl_power_ratings.py this only fits one regression, not two.

Unlike NFL/soccer, there's no free bundled real-world total line to
predict against -- nba_api doesn't carry bookmaker data. Matches the
established pattern for soccer's own count-based props (corners/SOT in
props.py): candidate_lines() offers several half-point lines spaced
around the model's own predicted total, and the caller only publishes
the ones where prob_over() actually lands in a confident band -- the
line exactly at the prediction itself is deliberately never one of
them, since prob_over there is tautologically ~0.5 by construction.

level[home] + level[away] + intercept ~ home_score + away_score,
fit via ridge regression -- same mechanics as nfl_power_ratings.py's
total half, a blended scoring-environment rating rather than a full
pace-adjusted offensive/defensive-rating decomposition (that fuller
"efficiency x pace" design from the original ticket is real, separate
future work once this baseline is live and has graded data to compare
against).

Deliberately NOT calibrated (Normal-approximation probabilities only)
-- no graded NBA history to calibrate against before this season's
games are played, same honest gap nfl_power_ratings.py documents.

Usage:
    model = NBAPowerRatings(alpha=5.0)
    model.fit(games_df)          # cols: home, away, home_score, away_score
    for line in model.candidate_lines("BOS", "MIA"):
        p = model.prob_over("BOS", "MIA", line)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm


class NBAPowerRatings:
    def __init__(self, alpha: float = 5.0):
        self.alpha = alpha
        self.teams: list[str] = []
        self.total_ratings: dict[str, float] = {}
        self.total_intercept = 0.0
        self.sigma_total = 12.0  # overwritten by fit()

    def fit(self, df: pd.DataFrame) -> "NBAPowerRatings":
        df = df.dropna(subset=["home_score", "away_score"]).copy()
        if df.empty:
            raise ValueError("no completed games to fit on")
        self.teams = sorted(set(df["home"]) | set(df["away"]))
        idx = {t: i for i, t in enumerate(self.teams)}
        n_teams = len(self.teams)
        n_games = len(df)

        X = np.zeros((n_games, n_teams + 1))
        y = np.zeros(n_games)
        for row_i, (_, g) in enumerate(df.iterrows()):
            X[row_i, idx[g["home"]]] = 1.0
            X[row_i, idx[g["away"]]] = 1.0
            X[row_i, n_teams] = 1.0
            y[row_i] = g["home_score"] + g["away_score"]

        penalty = self.alpha * np.eye(n_teams + 1)
        penalty[-1, -1] = 0.0
        beta = np.linalg.solve(X.T @ X + penalty, X.T @ y)

        self.total_ratings = {t: beta[idx[t]] for t in self.teams}
        self.total_intercept = beta[n_teams]
        resid = y - X @ beta
        self.sigma_total = float(np.std(resid)) if n_games > n_teams else self.sigma_total
        return self

    def predicted_total(self, home: str, away: str) -> float:
        home_t = self.total_ratings.get(home, 0.0)
        away_t = self.total_ratings.get(away, 0.0)
        return home_t + away_t + self.total_intercept

    def prob_over(self, home: str, away: str, line: float) -> float:
        pred = self.predicted_total(home, away)
        return float(1 - norm.cdf(line, loc=pred, scale=self.sigma_total))

    def candidate_lines(self, home: str, away: str,
                        offsets: tuple[float, ...] = (-6, -4, -2, 2, 4, 6)) -> list[float]:
        """Half-point lines spaced around the model's own predicted total
        -- there's no real market total to anchor to (nba_api carries no
        bookmaker data), so the caller (generate_nba_slate.py) evaluates
        prob_over() at each of these and only publishes the ones that
        land in a genuinely confident band, exactly like corners/SOT's
        fixed-line-list treatment in generate_slate.py. The line AT the
        prediction itself is deliberately excluded -- prob_over there is
        tautologically ~0.5 by construction, not a real editorial claim."""
        pred = self.predicted_total(home, away)
        lines = []
        for offset in offsets:
            raw = pred + offset
            line = round(raw * 2) / 2
            if line == round(line):  # never a whole-number line (avoids a push)
                line += 0.5
            lines.append(line)
        return lines
