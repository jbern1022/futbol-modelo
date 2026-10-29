"""
ADR-020 evidence gates: 350 per band to evaluate, 750 total for a meaningful
evaluation, calibration tolerance +/-5 points until EVERY evaluated band has
1,250 live graded predictions, then +/-3. Counts and intervals are always
reported; 1,250 alone is not claimed to be enough precision.
"""
import numpy as np
import pytest

from evaluation.evidence import (
    MATURE_N, MIN_BAND_N, MIN_TOTAL_N, TOL_FINAL, TOL_INTERIM,
    evaluate_cohort, wilson_interval,
)


def _cohort(n, stated, realized, seed=0):
    """n predictions all stated at `stated`, exactly round(n*realized) hits."""
    hits = int(round(n * realized))
    y = np.array([1] * hits + [0] * (n - hits))
    np.random.default_rng(seed).shuffle(y)
    return np.full(n, stated), y


def _stack(*parts):
    return np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts])


def test_constants_match_the_approved_gates():
    assert (MIN_BAND_N, MIN_TOTAL_N, MATURE_N) == (350, 750, 1250)
    assert (TOL_INTERIM, TOL_FINAL) == (0.05, 0.03)


def test_wilson_interval_basic_properties():
    lo, hi = wilson_interval(50, 100)
    assert lo < 0.5 < hi and 0.40 < lo and hi < 0.60
    lo0, hi0 = wilson_interval(0, 40)
    assert lo0 == 0.0 and 0 < hi0 < 0.15
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_below_total_gate_is_insufficient_evidence():
    p, y = _stack(_cohort(400, 0.65, 0.65), _cohort(300, 0.85, 0.85))  # 700 < 750
    r = evaluate_cohort(p, y)
    assert r["status"] == "INSUFFICIENT_EVIDENCE"
    assert r["n_total"] == 700


def test_bands_under_350_are_not_evaluated_but_reported():
    p, y = _stack(_cohort(500, 0.65, 0.65), _cohort(300, 0.85, 0.85))
    r = evaluate_cohort(p, y)
    assert r["status"] == "EVALUATED"
    by = {b["band"]: b for b in r["bands"]}
    assert by[7]["evaluated"] is True and by[9]["evaluated"] is False
    assert by[9]["n"] == 300 and "gap" not in by[9]


def test_interim_tolerance_five_points():
    p, y = _stack(_cohort(400, 0.65, 0.69), _cohort(400, 0.85, 0.80))  # +4, -5 (boundary)
    r = evaluate_cohort(p, y)
    assert r["tolerance"] == TOL_INTERIM and r["tolerance_regime"] == "interim"
    assert all(b["within_tolerance"] for b in r["bands"])
    p2, y2 = _stack(_cohort(400, 0.65, 0.72), _cohort(400, 0.85, 0.85))  # +7
    r2 = evaluate_cohort(p2, y2)
    assert not {b["band"]: b for b in r2["bands"]}[7]["within_tolerance"]
    assert r2["all_evaluated_bands_within_tolerance"] is False


def test_final_tolerance_needs_every_evaluated_band_at_1250():
    big = _cohort(1300, 0.65, 0.65)
    small = _cohort(400, 0.85, 0.85)  # evaluated but < 1250
    r = evaluate_cohort(*_stack(big, small))
    assert r["tolerance_regime"] == "interim"
    r2 = evaluate_cohort(*_stack(big, _cohort(1300, 0.85, 0.85)))
    assert r2["tolerance"] == TOL_FINAL and r2["tolerance_regime"] == "final"


def test_under_gate_band_does_not_block_final_regime():
    # a band below 350 is not evaluated, so it cannot hold the others back
    r = evaluate_cohort(*_stack(_cohort(1300, 0.65, 0.65), _cohort(1300, 0.75, 0.75), _cohort(100, 0.95, 0.95)))
    assert r["tolerance_regime"] == "final"


def test_final_regime_flags_a_four_point_gap():
    r = evaluate_cohort(*_stack(_cohort(1300, 0.65, 0.69), _cohort(1300, 0.85, 0.85)))
    assert r["tolerance"] == TOL_FINAL
    assert not {b["band"]: b for b in r["bands"]}[7]["within_tolerance"]


def test_reports_interval_and_precision_warning_not_a_pass_by_count():
    r = evaluate_cohort(*_stack(_cohort(1300, 0.65, 0.65), _cohort(1300, 0.85, 0.85)))
    b = r["bands"][0]
    assert b["ci_low"] < b["realized"] < b["ci_high"]
    assert b["ci_half_width"] > 0
    # at n=1300 the half-width (~2.6 pts) is not safely inside a 3-point tolerance
    assert "precision_ok" in b and isinstance(b["precision_ok"], bool)
    assert b["precision_ok"] == (b["ci_half_width"] <= r["tolerance"])


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        evaluate_cohort(np.array([0.5, 1.2]), np.array([1, 0]))
    with pytest.raises(ValueError):
        evaluate_cohort(np.array([0.5]), np.array([1, 0]))
