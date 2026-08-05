"""
Secondary-market ("props") count models: team corners, shots on target.

One LightGBM Poisson regressor per market predicting the expected count,
converted to over/under probabilities via a Poisson layer, then calibrated
with isotonic regression fit on OUT-OF-FOLD predictions.

Why this shape:
  - Counts (corners, shots on target) are naturally Poisson-ish.
  - A GBM captures style and opponent interactions raw Poisson cannot.
  - The isotonic calibrator is what makes a stated probability honest. Raw
    Poisson tail probabilities are systematically miscalibrated, and the
    calibrator is fit only on predictions the model did not train on — fitting
    it on training-fold predictions would learn the model's overfit and
    calibrate to a lie.

This module is the single source of truth for how a props model is trained,
calibrated, persisted and applied. An earlier version of this file was never
imported by anything: the live slate generator reimplemented a weaker variant
inline with no calibration and no baseline gate, which is how uncalibrated
probabilities reached the ledger. Prediction code should load a PropsModel and
call predict_over; it should not fit its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import TimeSeriesSplit

try:
    import joblib
except ImportError:  # pragma: no cover - joblib ships with scikit-learn
    joblib = None

try:
    import lightgbm as lgb
except ImportError:  # keeps the module importable for schema/consumer tests
    lgb = None

ARTIFACT_VERSION = 1

# Single source of truth for the props markets. Training and inference both
# read this, so a feature list cannot drift between the model that was fit and
# the code that applies it.
#
# `features` excludes xg_for_r5 / xg_against_r5 and includes league_id.
# team_match_stats.xg is ~99% populated for EPL/SERIE_A (Understat) and 0% for
# MLS (API-Football's tier does not supply it), so selecting xG and calling
# dropna() silently discarded every MLS row. Measured with
# scripts/compare_props_features.py against production: that model was worse
# than a naive baseline on MLS for both markets. Dropping xG costs ~0.002
# logloss on European holdout rows (noise); adding league_id, so the model can
# learn per-league scoring rates instead of averaging across them, improved
# every league/market cell tested. Revisit once MLS has real xG.
#
# `noun` completes the statement written to the ledger: "Inter over 4.5
# corners". Statements are immutable, so the subject has to be baked in at
# write time.
MARKETS: dict[str, dict] = {
    "CORNERS": {
        "target_col": "corners",
        "lines": [3.5, 4.5, 5.5, 6.5],
        "noun": "corners",
        "features": ["corners_for_r5", "corners_against_r5",
                     "shots_for_r5", "shots_against_r5",
                     "rest_days", "is_home", "league_id"],
        "categorical": ["league_id"],
    },
    "SOT": {
        "target_col": "shots_on_target",
        "lines": [2.5, 3.5, 4.5, 5.5],
        "noun": "shots on target",
        "features": ["sot_for_r5", "sot_against_r5",
                     "shots_for_r5", "shots_against_r5",
                     "rest_days", "is_home", "league_id"],
        "categorical": ["league_id"],
    },
}


def for_market(market: str) -> "PropsModel":
    """An unfitted PropsModel configured for one of the registered markets."""
    spec = MARKETS[market]
    return PropsModel(market=market, features=spec["features"],
                      lines=spec["lines"], categorical=spec["categorical"])


def artifact_path(model_dir: str | Path, market: str) -> Path:
    return Path(model_dir) / f"props_{market.lower()}.joblib"

LGB_PARAMS = dict(
    objective="poisson",
    n_estimators=300,
    learning_rate=0.03,
    num_leaves=20,
    min_child_samples=30,
    subsample=0.8,
    colsample_bytree=0.8,
    verbose=-1,
)

# Isotonic regression needs both outcomes present and enough support to mean
# anything. Below this, the raw Poisson probability is used unchanged rather
# than a calibrator fit on a handful of points.
MIN_CALIBRATION_SAMPLES = 50


@dataclass
class PropsModel:
    market: str
    features: list[str]
    lines: list[float]
    categorical: list[str] = field(default_factory=list)
    model: Any = None
    calibrators: dict[float, IsotonicRegression] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    # ---------- training ----------

    def fit(self, df: pd.DataFrame, target: str,
            n_splits: int = 5) -> "PropsModel":
        """
        `df` must be sorted by match date — the calibration split is temporal,
        so out-of-order rows would leak future information into the folds.
        """
        if lgb is None:
            raise RuntimeError("lightgbm is required to fit a PropsModel")

        d = df.dropna(subset=self.features + [target]).copy()
        if d.empty:
            raise ValueError(f"no rows left to train {self.market} after dropna")
        for col in self.categorical:
            d[col] = d[col].astype(int)

        X, y = d[self.features], d[target].to_numpy()

        # Out-of-fold expected counts, so calibration never sees a prediction
        # the model was trained on.
        oof = np.full(len(d), np.nan)
        for train_idx, test_idx in TimeSeriesSplit(n_splits=n_splits).split(X):
            fold = lgb.LGBMRegressor(**LGB_PARAMS)
            fold.fit(X.iloc[train_idx], y[train_idx], **self._fit_kwargs())
            oof[test_idx] = fold.predict(X.iloc[test_idx])

        self.model = lgb.LGBMRegressor(**LGB_PARAMS)
        self.model.fit(X, y, **self._fit_kwargs())

        self._fit_calibrators(oof, y)
        self.metadata.update({
            "artifact_version": ARTIFACT_VERSION,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "n_train": int(len(d)),
            "target": target,
            "features": list(self.features),
            "categorical": list(self.categorical),
            "lines": list(self.lines),
            "lgb_params": dict(LGB_PARAMS),
            "calibrated_lines": sorted(self.calibrators),
        })
        return self

    def _fit_kwargs(self) -> dict:
        return {"categorical_feature": self.categorical} if self.categorical else {}

    def _fit_calibrators(self, oof: np.ndarray, y: np.ndarray) -> None:
        mask = ~np.isnan(oof)
        if mask.sum() < MIN_CALIBRATION_SAMPLES:
            return
        raw_all, actual_all = oof[mask], y[mask]
        for line in self.lines:
            raw = self._poisson_over(raw_all, line)
            actual = (actual_all > line).astype(int)
            # Isotonic needs both classes; a line every observation clears (or
            # none does) carries no information to calibrate against.
            if len(np.unique(actual)) < 2:
                continue
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
            iso.fit(raw, actual)
            self.calibrators[float(line)] = iso

    @staticmethod
    def _poisson_over(mu: np.ndarray | float, line: float) -> np.ndarray | float:
        """P(count > line) under Poisson(mu). Half-lines make this exact."""
        return 1 - poisson.cdf(np.floor(line), np.clip(mu, 1e-6, None))

    # ---------- inference ----------

    def expected(self, X_row: pd.DataFrame) -> float:
        return float(np.clip(self.model.predict(X_row[self.features])[0], 1e-6, None))

    def predict_over(self, X_row: pd.DataFrame, line: float) -> float:
        """Calibrated P(count > line). Falls back to the raw Poisson
        probability when no calibrator was fit for this line."""
        raw = float(self._poisson_over(self.expected(X_row), line))
        iso = self.calibrators.get(float(line))
        if iso is None:
            return raw
        return float(np.clip(iso.predict([raw])[0], 0.01, 0.99))

    def is_calibrated(self, line: float) -> bool:
        return float(line) in self.calibrators

    # ---------- persistence ----------

    def save(self, path: str | Path) -> Path:
        if joblib is None:
            raise RuntimeError("joblib is required to persist a PropsModel")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> "PropsModel":
        if joblib is None:
            raise RuntimeError("joblib is required to load a PropsModel")
        obj = joblib.load(Path(path))
        if not isinstance(obj, cls):
            raise TypeError(f"{path} does not contain a PropsModel")
        stored = obj.metadata.get("artifact_version")
        if stored != ARTIFACT_VERSION:
            raise ValueError(
                f"{path} was written by artifact version {stored!r}, this code "
                f"expects {ARTIFACT_VERSION}. Retrain rather than loading it."
            )
        return obj


# ---------- evaluation helpers, shared by training and analysis ----------

def poisson_logloss(y: np.ndarray, mu: np.ndarray) -> float:
    return float(-poisson.logpmf(y, np.clip(mu, 1e-6, None)).mean())


def baseline_logloss(y_test: np.ndarray, train_mean: float) -> float:
    """The bar a model must clear: predict the training-set mean every time."""
    return poisson_logloss(y_test, np.full(len(y_test), train_mean))
