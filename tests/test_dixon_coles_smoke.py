"""
Smoke test for DixonColes.fit() on synthetic data.

The property-based invariant tests (test_dixon_coles_invariants.py) bypass
fit() entirely — they inject params directly. This test actually calls fit()
to catch wiring bugs (wrong column name, bad optimizer call, missing
normalisation) that properties-on-params would never see.
"""
import numpy as np
import pandas as pd
import pytest

from models.dixon_coles import DixonColes, derive_markets


@pytest.fixture(scope="module")
def fitted_model():
    rng = np.random.default_rng(0)
    n = 50
    teams = ["Home", "Away", "Third", "Fourth"]
    # Build pairs where home != away by cycling through all distinct combos
    pairs = [(h, a) for h in teams for a in teams if h != a]
    pair_idx = rng.integers(0, len(pairs), size=n)
    home = np.array([pairs[i][0] for i in pair_idx])
    away = np.array([pairs[i][1] for i in pair_idx])
    dates = pd.date_range("2024-08-01", periods=n, freq="7D")
    hg = rng.poisson(1.5, size=n)
    ag = rng.poisson(1.1, size=n)
    df = pd.DataFrame({"date": dates, "home": home, "away": away, "hg": hg, "ag": ag})
    model = DixonColes(xi=0.0018)
    model.fit(df)
    return model


def test_fit_populates_params(fitted_model):
    assert fitted_model.params is not None
    assert len(fitted_model.params) > 0


def test_fit_populates_teams(fitted_model):
    assert len(fitted_model.teams) >= 2


def test_score_matrix_sums_to_one(fitted_model):
    teams = fitted_model.teams
    matrix = fitted_model.score_matrix(teams[0], teams[1])
    assert abs(matrix.sum() - 1.0) < 1e-6


def test_1x2_sums_to_one(fitted_model):
    teams = fitted_model.teams
    markets = derive_markets(fitted_model.predict(teams[0], teams[1]))
    total = markets["home_win"] + markets["draw"] + markets["away_win"]
    assert abs(total - 1.0) < 1e-9


def test_all_market_probs_in_unit_interval(fitted_model):
    teams = fitted_model.teams
    markets = derive_markets(fitted_model.predict(teams[0], teams[1]))
    for key, value in markets.items():
        if key == "top_scorelines":
            continue
        assert -1e-9 <= value <= 1 + 1e-9, f"{key}={value} out of [0,1]"
