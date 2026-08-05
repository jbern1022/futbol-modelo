"""
PropsModel: calibration, persistence, and the invariants a probability model
has to hold regardless of what it learned.

No database. Data is synthetic but structured — the count depends on the
features, so a model that ignores them will fail the "beats the baseline"
test the way a real bad model would.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")

from models.props import (  # noqa: E402
    PropsModel,
    baseline_logloss,
    poisson_logloss,
)

FEATURES = ["for_r5", "against_r5", "is_home", "league_id"]
LINES = [2.5, 3.5, 4.5, 5.5]


def make_data(n: int = 1200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    league = rng.integers(0, 3, n)
    for_r5 = rng.normal(5, 1.2, n) + league  # league genuinely shifts the rate
    against_r5 = rng.normal(5, 1.2, n)
    is_home = rng.integers(0, 2, n)
    mu = np.clip(0.55 * for_r5 + 0.25 * against_r5 + 0.4 * is_home, 0.3, None)
    return pd.DataFrame({
        "for_r5": for_r5,
        "against_r5": against_r5,
        "is_home": is_home.astype(float),
        "league_id": league,
        "y": rng.poisson(mu),
    })


@pytest.fixture(scope="module")
def trained() -> tuple[PropsModel, pd.DataFrame, pd.DataFrame]:
    df = make_data()
    train, test = df.iloc[:900], df.iloc[900:]
    m = PropsModel(market="TEST", features=FEATURES, lines=LINES,
                   categorical=["league_id"]).fit(train, "y")
    return m, train, test


# ---------- probability invariants ----------

def test_predicted_probabilities_are_valid(trained):
    model, _, test = trained
    for i in range(30):
        row = test.iloc[[i]]
        for line in LINES:
            p = model.predict_over(row, line)
            assert 0.0 < p < 1.0, (line, p)


def test_probability_is_non_increasing_in_the_line(trained):
    """P(count > 2.5) must be at least P(count > 5.5). Calibration is fit per
    line independently, so this is a real risk, not a tautology."""
    model, _, test = trained
    violations = 0
    for i in range(60):
        row = test.iloc[[i]]
        probs = [model.predict_over(row, line) for line in sorted(LINES)]
        if any(b > a + 1e-9 for a, b in zip(probs, probs[1:])):
            violations += 1
    assert violations == 0, f"{violations}/60 rows had P(over) rising with the line"


def test_expected_count_is_positive(trained):
    model, _, test = trained
    assert all(model.expected(test.iloc[[i]]) > 0 for i in range(20))


# ---------- calibration ----------

def test_calibrators_were_fit(trained):
    model, _, _ = trained
    assert model.calibrators, "no calibrators fit at all"
    assert all(model.is_calibrated(ln) for ln in model.metadata["calibrated_lines"])


def test_calibration_does_not_degrade_brier_score(trained):
    """
    The calibrator's whole justification. Compare Brier on held-out rows for
    raw Poisson probabilities vs calibrated ones, pooled over lines.
    """
    model, _, test = trained
    raw_se, cal_se = [], []
    for i in range(len(test)):
        row = test.iloc[[i]]
        mu = model.expected(row)
        for line in LINES:
            actual = int(test.iloc[i]["y"] > line)
            raw = float(model._poisson_over(mu, line))
            cal = model.predict_over(row, line)
            raw_se.append((raw - actual) ** 2)
            cal_se.append((cal - actual) ** 2)
    assert np.mean(cal_se) <= np.mean(raw_se) + 0.005


def test_uncalibrated_line_falls_back_to_raw(trained):
    model, _, test = trained
    row = test.iloc[[0]]
    unseen = 99.5
    assert not model.is_calibrated(unseen)
    expected = float(model._poisson_over(model.expected(row), unseen))
    assert model.predict_over(row, unseen) == pytest.approx(expected)


def test_calibration_is_skipped_when_a_line_has_one_outcome():
    """A line no observation ever clears carries nothing to calibrate."""
    df = make_data(400)
    m = PropsModel(market="TEST", features=FEATURES, lines=[0.5, 500.5],
                   categorical=["league_id"]).fit(df, "y")
    assert not m.is_calibrated(500.5)


# ---------- the shipping gate ----------

def test_model_beats_the_naive_baseline(trained):
    """If this fails on structured data the model is not learning, and the
    training entry point is right to refuse to ship it."""
    model, train, test = trained
    mu = np.array([model.expected(test.iloc[[i]]) for i in range(len(test))])
    y = test["y"].to_numpy()
    assert poisson_logloss(y, mu) < baseline_logloss(y, train["y"].mean())


# ---------- persistence ----------

def test_save_load_round_trip_preserves_predictions(trained, tmp_path):
    model, _, test = trained
    path = model.save(tmp_path / "test.joblib")
    reloaded = PropsModel.load(path)

    assert reloaded.features == model.features
    assert reloaded.market == model.market
    assert sorted(reloaded.calibrators) == sorted(model.calibrators)
    for i in range(20):
        row = test.iloc[[i]]
        for line in LINES:
            assert reloaded.predict_over(row, line) == pytest.approx(
                model.predict_over(row, line))


def test_load_rejects_a_mismatched_artifact_version(trained, tmp_path):
    """A stale artifact must fail loudly rather than predict with the wrong
    feature contract."""
    model, _, _ = trained
    path = model.save(tmp_path / "stale.joblib")
    stale = PropsModel.load(path)
    stale.metadata["artifact_version"] = 0
    stale.save(path)
    with pytest.raises(ValueError, match="artifact version"):
        PropsModel.load(path)


def test_metadata_records_what_shipped(trained):
    model, train, _ = trained
    md = model.metadata
    assert md["n_train"] == len(train.dropna(subset=FEATURES + ["y"]))
    assert md["features"] == FEATURES
    assert md["target"] == "y"
    assert md["trained_at"].endswith("+00:00")


# ---------- failure modes ----------

def test_fit_refuses_an_empty_frame():
    empty = make_data(10).iloc[:0]
    with pytest.raises(ValueError, match="no rows left"):
        PropsModel(market="TEST", features=FEATURES, lines=LINES).fit(empty, "y")
