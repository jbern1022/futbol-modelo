"""
Secondary-market models ("props"): team corners, team shots,
player shots, GK saves. One LightGBM regressor per market predicting
the expected count, converted to over/under probabilities via a
Poisson/negative-binomial layer, then calibrated with isotonic regression.

Why this shape:
  - Counts (corners, shots, saves) are naturally Poisson-ish.
  - GBM captures style/opponent interactions raw Poisson can't.
  - The isotonic calibrator is what makes stated probabilities honest —
    it is fit on out-of-fold predictions, never training folds.

Trains fine on CPU; move to GPU LightGBM or the neural tier (v3) later.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import TimeSeriesSplit

try:
    import lightgbm as lgb
except ImportError:  # keep importable without the dep for schema tests
    lgb = None

# ------------------------------------------------------------------
# Feature spec — built from team_match_stats / player_match_stats
# All features are AS-OF the match date (no leakage; enforce in SQL).
# ------------------------------------------------------------------

TEAM_FEATURES = [
    # rolling means, windows 5 and 10, for the subject team
    "corners_for_r5", "corners_for_r10",
    "corners_against_r5", "corners_against_r10",
    "shots_for_r5", "shots_for_r10",
    "shots_against_r5", "shots_against_r10",
    "xg_for_r5", "xg_against_r5",
    "possession_r5", "ppda_r5", "deep_completions_r5",
    # opponent mirror
    "opp_corners_against_r5", "opp_shots_against_r5",
    "opp_xg_against_r5", "opp_ppda_r5", "opp_possession_r5",
    # context
    "is_home", "rest_days", "opp_rest_days",
    "league_code",            # categorical — enables cross-league training
]

PLAYER_FEATURES = [
    "p_shots_r5", "p_shots_r10", "p_minutes_r5",
    "p_xg_r5", "p_goals_r10", "p_key_passes_r5",
    "team_xg_for_r5", "opp_xg_against_r5", "opp_shots_against_r5",
    "is_home", "league_code",
    # GK market
    "p_saves_r5", "opp_shots_on_target_r5", "opp_xg_for_r5",
]

LGB_PARAMS = dict(
    objective="poisson",       # count target
    n_estimators=600,
    learning_rate=0.03,
    num_leaves=31,
    min_child_samples=40,
    subsample=0.8,
    colsample_bytree=0.8,
    verbose=-1,
)


@dataclass
class PropsModel:
    market: str                                   # 'TEAM_CORNERS', 'PLAYER_SHOTS', ...
    features: list[str] = field(default_factory=lambda: TEAM_FEATURES)
    model: object = None
    calibrators: dict = field(default_factory=dict)   # line -> IsotonicRegression

    # ---------- training ----------

    def fit(self, df: pd.DataFrame, target: str, lines: list[float]):
        """
        df must be sorted by match date. `target` is the observed count
        (e.g. corners). Calibrators are fit per line on out-of-fold preds.
        """
        X = df[self.features]
        y = df[target].to_numpy()

        # out-of-fold expected counts for honest calibration
        oof_mu = np.full(len(df), np.nan)
        tscv = TimeSeriesSplit(n_splits=5)
        for tr, te in tscv.split(X):
            m = lgb.LGBMRegressor(**LGB_PARAMS)
            m.fit(X.iloc[tr], y[tr], categorical_feature=["league_code"])
            oof_mu[te] = m.predict(X.iloc[te])

        # final model on all data
        self.model = lgb.LGBMRegressor(**LGB_PARAMS)
        self.model.fit(X, y, categorical_feature=["league_code"])

        # calibrate P(over line) per line
        mask = ~np.isnan(oof_mu)
        for line in lines:
            raw_p = 1 - poisson.cdf(np.floor(line), oof_mu[mask])
            actual = (y[mask] > line).astype(int)
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
            iso.fit(raw_p, actual)
            self.calibrators[line] = iso
        return self

    # ---------- inference ----------

    def predict_over(self, X_row: pd.DataFrame, line: float) -> float:
        """Calibrated P(count > line) for one fixture row."""
        mu = float(self.model.predict(X_row)[0])
        raw = float(1 - poisson.cdf(np.floor(line), mu))
        iso = self.calibrators.get(line)
        return float(iso.predict([raw])[0]) if iso else raw

    def expected(self, X_row: pd.DataFrame) -> float:
        return float(self.model.predict(X_row)[0])


# Market registry: market -> (target column, standard lines, feature set)
MARKETS = {
    "TEAM_CORNERS":  ("corners",         [3.5, 4.5, 5.5, 6.5], TEAM_FEATURES),
    "TEAM_SHOTS":    ("shots",           [9.5, 11.5, 13.5, 15.5], TEAM_FEATURES),
    "TEAM_SOT":      ("shots_on_target", [2.5, 3.5, 4.5, 5.5], TEAM_FEATURES),
    "PLAYER_SHOTS":  ("p_shots",         [0.5, 1.5, 2.5, 3.5], PLAYER_FEATURES),
    "PLAYER_SAVES":  ("p_saves",         [1.5, 2.5, 3.5, 4.5], PLAYER_FEATURES),
}
