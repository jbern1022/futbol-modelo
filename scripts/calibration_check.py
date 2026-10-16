"""
Sampling-error-aware calibration check for binary probabilities.

Replaces the "any 0.1-wide band with n >= 100 differs by more than 0.07" rule
used in the 2026-10-15 props pre-registrations, which false-fails about half
the time under perfect calibration at these sample sizes (registry, "Result,
Bundesliga in the training pool with no offset").

For one line (probabilities p, outcomes y, one cluster id per row):
  shift a : y ~ Bernoulli(expit(logit p + a))      calibration-in-the-large
  slope b : y ~ Bernoulli(expit(c + b * logit p))  spread of the probabilities
Intervals are percentile intervals from a bootstrap that resamples whole
clusters (here: matches, so both team rows of a match move together).

A line FAILS only if it is both statistically distinguishable from perfect
calibration AND materially off (see FAIL RULE). All fits are vectorised
Newton iterations, one row of weights per bootstrap draw.
"""
from __future__ import annotations

import numpy as np

CLIP = (0.01, 0.99)       # the isotonic calibrators' own output range
CI_LEVEL = 99.0           # percent; 8 tests (shift and slope on 4 lines) per market
SHIFT_TOL = 0.15          # logit units: about 3.7 points at p = 0.5
SLOPE_TOL = 0.20          # |b - 1|
N_BOOT = 1000


def _expit(x):
    return 1.0 / (1.0 + np.exp(-x))


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, *CLIP)
    return np.log(p / (1.0 - p))


def fit_shift(y: np.ndarray, z: np.ndarray, w: np.ndarray, iters: int = 25) -> np.ndarray:
    """MLE of a per weight row. y, z: (n,), w: (B, n) -> (B,)."""
    a = np.zeros(w.shape[0])
    for _ in range(iters):
        p = _expit(z[None, :] + a[:, None])
        g = (w * (y[None, :] - p)).sum(axis=1)
        h = np.maximum((w * p * (1 - p)).sum(axis=1), 1e-9)
        step = np.clip(g / h, -2, 2)
        a = a + step
        if np.max(np.abs(step)) < 1e-7:
            break
    return a


def fit_slope(y: np.ndarray, z: np.ndarray, w: np.ndarray, iters: int = 30) -> np.ndarray:
    """MLE of the slope b in logistic(c + b z) per weight row -> (B,)."""
    B = w.shape[0]
    c, b = np.zeros(B), np.ones(B)
    for _ in range(iters):
        p = _expit(c[:, None] + b[:, None] * z[None, :])
        r = w * (y[None, :] - p)
        gc, gb = r.sum(axis=1), (r * z[None, :]).sum(axis=1)
        v = w * p * (1 - p)
        hcc, hcb, hbb = v.sum(axis=1), (v * z[None, :]).sum(axis=1), (v * z[None, :] ** 2).sum(axis=1)
        det = np.maximum(hcc * hbb - hcb ** 2, 1e-9)
        dc, db = (hbb * gc - hcb * gb) / det, (hcc * gb - hcb * gc) / det
        dc, db = np.clip(dc, -2, 2), np.clip(db, -2, 2)
        c, b = c + dc, b + db
        if max(np.max(np.abs(dc)), np.max(np.abs(db))) < 1e-7:
            break
    return b


def _cluster_weights(ids: np.ndarray, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """(n_boot, n) row weights: each draw resamples clusters with replacement."""
    uniq, inv = np.unique(ids, return_inverse=True)
    counts = rng.multinomial(len(uniq), np.full(len(uniq), 1.0 / len(uniq)), size=n_boot)
    return counts[:, inv].astype(float)


def assess(p: np.ndarray, y: np.ndarray, ids: np.ndarray, n_boot: int = N_BOOT, seed: int = 0) -> dict:
    """Point estimates, bootstrap intervals and the FAIL RULE for one line."""
    z = logit(p)
    y = y.astype(float)
    rng = np.random.default_rng(seed)
    w = np.vstack([np.ones((1, len(y))), _cluster_weights(ids, n_boot, rng)])
    a_all, b_all = fit_shift(y, z, w), fit_slope(y, z, w)
    lo, hi = (100 - CI_LEVEL) / 2, 100 - (100 - CI_LEVEL) / 2
    a, b = float(a_all[0]), float(b_all[0])
    a_ci = tuple(np.percentile(a_all[1:], [lo, hi]))
    b_ci = tuple(np.percentile(b_all[1:], [lo, hi]))
    shift_fail = (a_ci[0] > 0 or a_ci[1] < 0) and abs(a) > SHIFT_TOL
    slope_fail = (b_ci[0] > 1 or b_ci[1] < 1) and abs(b - 1) > SLOPE_TOL
    return {"shift": a, "shift_ci": a_ci, "slope": b, "slope_ci": b_ci,
            "shift_fail": bool(shift_fail), "slope_fail": bool(slope_fail),
            "fail": bool(shift_fail or slope_fail)}
