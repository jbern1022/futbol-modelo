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
from scipy.optimize import minimize
from scipy.stats import poisson as scipy_poisson

from models.dixon_coles import DixonColes, _tau, derive_markets


def _synthetic_matches():
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
    return pd.DataFrame({"date": dates, "home": home, "away": away, "hg": hg, "ag": ag})


@pytest.fixture(scope="module")
def fitted_model():
    model = DixonColes(xi=0.0018)
    model.fit(_synthetic_matches())
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


def _fit_with_original_scalar_tau_loop(df: pd.DataFrame, xi: float, reg: float = 0.0) -> np.ndarray:
    """Independent reimplementation of fit()'s nll() exactly as it read
    before _tau_vec existed -- scalar _tau() via a per-match Python list
    comprehension, not calling anything from dixon_coles.py's fit() itself.
    Same x0, same constraints, same optimizer call. Used only to prove the
    vectorized fit() converges to the same params, not to replace it."""
    df = df.dropna(subset=["hg", "ag"]).copy()
    teams = sorted(set(df["home"]) | set(df["away"]))
    n = len(teams)
    idx = {t: i for i, t in enumerate(teams)}

    home_i = df["home"].map(idx).to_numpy()
    away_i = df["away"].map(idx).to_numpy()
    hg = df["hg"].to_numpy(int)
    ag = df["ag"].to_numpy(int)
    days_ago = (df["date"].max() - df["date"]).dt.days.to_numpy()
    w = np.exp(-xi * days_ago)

    x0 = np.concatenate([np.zeros(n), np.zeros(n), [0.25], [-0.05]])

    def nll(p: np.ndarray) -> float:
        atk, dfn = p[:n], p[n:2 * n]
        gamma, rho = p[2 * n], p[2 * n + 1]
        lam = np.exp(atk[home_i] + dfn[away_i] + gamma)
        mu = np.exp(atk[away_i] + dfn[home_i])
        tau = np.array([
            _tau(x, y, l, m, rho)
            for x, y, l, m in zip(hg, ag, lam, mu)
        ])
        tau = np.clip(tau, 1e-10, None)
        ll = w * (
            np.log(tau)
            + scipy_poisson.logpmf(hg, lam)
            + scipy_poisson.logpmf(ag, mu)
        )
        penalty = reg * (np.sum(atk ** 2) + np.sum(dfn ** 2)) if reg else 0.0
        return -ll.sum() + penalty

    cons = [{"type": "eq", "fun": lambda p: p[:n].sum()}]
    res = minimize(nll, x0, constraints=cons, method="SLSQP",
                    options={"maxiter": 300, "ftol": 1e-8})
    return res.x


def test_fit_matches_pre_vectorization_snapshot():
    """The actual point of _tau_vec: prove fit() converges to the same
    params it always did. Not an approximate/vibes check -- same synthetic
    data, same optimizer settings, same x0, compared against an independent
    reimplementation of the exact pre-vectorization nll()."""
    df = _synthetic_matches()

    vectorized = DixonColes(xi=0.0018)
    vectorized.fit(df)

    original = _fit_with_original_scalar_tau_loop(df, xi=0.0018)

    np.testing.assert_allclose(vectorized.params, original, atol=1e-8)
