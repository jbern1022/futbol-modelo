"""
Sampling-error calibration criterion (scripts/calibration_check.py): it must
recover a known shift and slope, pass a well-calibrated model, and fail a
clearly miscalibrated one. Synthetic data only; fixed seeds.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from calibration_check import assess, logit  # noqa: E402

N = 2000
IDS = np.repeat(np.arange(N // 2), 2)  # two rows per "match"


def _draw(shift: float, slope: float, seed: int):
    rng = np.random.default_rng(seed)
    p = np.clip(rng.beta(3, 3, N), 0.05, 0.95)
    true_p = 1 / (1 + np.exp(-(shift + slope * logit(p))))
    return p, (rng.random(N) < true_p).astype(int)


def test_recovers_a_known_shift():
    p, y = _draw(0.30, 1.0, seed=1)
    r = assess(p, y, IDS, n_boot=300)
    assert 0.18 < r["shift"] < 0.42
    assert r["shift_ci"][0] > 0
    assert r["shift_fail"] and r["fail"]


def test_recovers_a_known_slope():
    p, y = _draw(0.0, 0.70, seed=2)
    r = assess(p, y, IDS, n_boot=300)
    assert 0.55 < r["slope"] < 0.85
    assert r["slope_ci"][1] < 1
    assert r["slope_fail"] and r["fail"]


def test_a_calibrated_model_passes():
    p, y = _draw(0.0, 1.0, seed=3)
    r = assess(p, y, IDS, n_boot=300)
    assert r["shift_ci"][0] < 0 < r["shift_ci"][1]
    assert r["slope_ci"][0] < 1 < r["slope_ci"][1]
    assert not r["fail"]


def test_a_real_but_small_error_is_not_a_failure():
    """Distinguishable from perfect but inside the materiality tolerance: no fail."""
    p, y = _draw(0.08, 1.0, seed=4)
    r = assess(p, y, IDS, n_boot=300)
    assert abs(r["shift"]) <= 0.15
    assert not r["shift_fail"]


def test_same_inputs_give_the_same_answer():
    p, y = _draw(0.0, 1.0, seed=5)
    assert assess(p, y, IDS, n_boot=200, seed=7) == assess(p, y, IDS, n_boot=200, seed=7)
