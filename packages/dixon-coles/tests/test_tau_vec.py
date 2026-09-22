"""Element-wise equivalence: _tau_vec must match scalar _tau exactly.

_tau_vec replaced a per-match Python-level list comprehension calling
scalar _tau() inside fit()'s nll() -- the actual optimizer hot path. This
proves the vectorized version isn't just "close," it's identical, for
every case _tau branches on plus the values fit() actually sees (arbitrary
non-negative goal counts, not just 0/1).
"""
import numpy as np
import pytest

from dixon_coles._model import _tau, _tau_vec

# (x, y) pairs covering every _tau branch (0,0)/(0,1)/(1,0)/(1,1) plus
# several higher scorelines that all fall through to the "return 1.0" case.
_SCORELINES = [(0, 0), (0, 1), (1, 0), (1, 1), (0, 2), (2, 0), (2, 2), (3, 1), (1, 3), (5, 4)]
_LAM_MU = [(0.6, 0.5), (1.2, 1.1), (2.8, 0.4), (0.9, 3.2), (1.5, 1.5)]
_RHOS = [-0.15, -0.05, 0.0, 0.05, 0.15]


@pytest.mark.parametrize("x,y", _SCORELINES)
@pytest.mark.parametrize("lam,mu", _LAM_MU)
@pytest.mark.parametrize("rho", _RHOS)
def test_tau_vec_matches_scalar_tau_single_element(x, y, lam, mu, rho):
    scalar = _tau(x, y, lam, mu, rho)
    vec = _tau_vec(np.array([x]), np.array([y]), np.array([lam]), np.array([mu]), rho)
    assert vec.shape == (1,)
    assert vec[0] == pytest.approx(scalar, abs=1e-15)


def test_tau_vec_matches_scalar_tau_whole_array_at_once():
    """The real call site passes a whole match dataset in one call, not one
    element at a time -- prove that batching doesn't change anything, e.g.
    via array-shape bugs in the boolean masks."""
    x = np.array([sl[0] for sl in _SCORELINES for _ in _LAM_MU])
    y = np.array([sl[1] for sl in _SCORELINES for _ in _LAM_MU])
    lam = np.array([lm[0] for _ in _SCORELINES for lm in _LAM_MU])
    mu = np.array([lm[1] for _ in _SCORELINES for lm in _LAM_MU])
    rho = 0.08

    vec = _tau_vec(x, y, lam, mu, rho)
    expected = np.array([_tau(int(xi), int(yi), li, mi, rho) for xi, yi, li, mi in zip(x, y, lam, mu)])
    np.testing.assert_allclose(vec, expected, atol=1e-15)
