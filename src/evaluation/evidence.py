"""
Evidence gates and calibration tolerance from ADR-020 (which keeps ADR-017's
350 / 750 / 1,250 gates and replaces its raw 80% accuracy target with a
calibration goal).

Pure functions over (stated probability, hit) arrays for ONE cohort: a single
league + market + model version, live graded predictions only. Backfills and
backtests must not be passed in; they never advance the evidence clock.

    350 per confidence band   minimum to evaluate that band's calibration
    750 in total              minimum for a meaningful cohort evaluation
    1,250 per evaluated band  every evaluated band at this size switches the
                              tolerance from +/-5 to the mandatory +/-3 points

Bands are the same deciles as the v_calibration view (SQL width_bucket(p, 0, 1, 10),
1-indexed). 1,250 does not by itself make a band precise enough, so each band
also reports its Wilson interval and whether the half-width fits the tolerance.
This module does not implement the projected-failure estimator (not selected,
Todoist 6hm2JMm4XrQJpJcf) nor On Track / At Risk labels.
"""
from __future__ import annotations

import math

import numpy as np

MIN_BAND_N = 350
MIN_TOTAL_N = 750
MATURE_N = 1250
TOL_INTERIM = 0.05
TOL_FINAL = 0.03
Z95 = 1.959963984540054
_EPS = 1e-9


def wilson_interval(hits: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _band(p: np.ndarray) -> np.ndarray:
    return np.minimum((p * 10).astype(int), 9) + 1


def evaluate_cohort(probs: np.ndarray, hits: np.ndarray) -> dict:
    p = np.asarray(probs, dtype=float)
    y = np.asarray(hits, dtype=int)
    if p.shape != y.shape or p.ndim != 1:
        raise ValueError("probs and hits must be 1-D arrays of equal length")
    if len(p) and (p.min() < 0.0 or p.max() > 1.0):
        raise ValueError("probabilities must be within [0, 1]")

    bands = []
    band_ids = _band(p) if len(p) else np.array([], dtype=int)
    for b in sorted(set(band_ids.tolist())):
        m = band_ids == b
        n = int(m.sum())
        row = {"band": int(b), "n": n, "evaluated": n >= MIN_BAND_N}
        if row["evaluated"]:
            h = int(y[m].sum())
            realized, stated = h / n, float(p[m].mean())
            lo, hi = wilson_interval(h, n)
            row.update(avg_stated=stated, realized=realized, gap=realized - stated,
                       ci_low=lo, ci_high=hi, ci_half_width=(hi - lo) / 2)
        bands.append(row)

    n_total = int(len(p))
    evaluated = [r for r in bands if r["evaluated"]]
    meaningful = n_total >= MIN_TOTAL_N and bool(evaluated)
    final = meaningful and all(r["n"] >= MATURE_N for r in evaluated)
    tol = TOL_FINAL if final else TOL_INTERIM
    for r in evaluated:
        r["within_tolerance"] = abs(r["gap"]) <= tol + _EPS
        r["precision_ok"] = r["ci_half_width"] <= tol + _EPS
    return {
        "status": "EVALUATED" if meaningful else "INSUFFICIENT_EVIDENCE",
        "n_total": n_total,
        "tolerance": tol,
        "tolerance_regime": "final" if final else "interim",
        "bands": bands,
        "all_evaluated_bands_within_tolerance": (
            all(r["within_tolerance"] for r in evaluated) if meaningful else None),
    }
