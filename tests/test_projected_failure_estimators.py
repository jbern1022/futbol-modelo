"""Sanity of the simulation's estimators (scripts/experiment_projected_failure_estimators.py)."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import experiment_projected_failure_estimators as ex  # noqa: E402


def _series(rate, n=600, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.uniform(size=(1, ex.N)) < rate).astype(np.int8)


@pytest.mark.parametrize("est", ex.ESTIMATORS)
def test_probabilities_are_in_unit_interval_and_order_with_the_observed_rate(est):
    on = ex.p_success(est, _series(ex.PBAR), 600)
    far = ex.p_success(est, _series(ex.PBAR - 0.10), 600)
    assert 0.0 <= float(on[0]) <= 1.0 and 0.0 <= float(far[0]) <= 1.0
    assert float(on[0]) > float(far[0])


@pytest.mark.parametrize("est", ex.ESTIMATORS)
def test_a_band_already_far_off_is_flagged_and_one_on_target_is_not(est):
    assert float(ex.p_success(est, _series(ex.PBAR - 0.12), 800)[0]) < ex.ALPHA
    assert float(ex.p_success(est, _series(ex.PBAR), 800, )[0]) > ex.ALPHA


def test_simulation_is_reproducible_and_dependence_widens_the_spread():
    a = ex.run(200, 0.12, 0.0, seed=1)
    b = ex.run(200, 0.12, 0.0, seed=1)
    assert a == b
    assert ex.run(400, 0.25, 0.0, seed=2)["passes"] < ex.run(400, 0.0, 0.0, seed=2)["passes"]
