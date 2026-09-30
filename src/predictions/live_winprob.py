"""
In-play win-probability (ADR-011). Conditions Dixon-Coles' fitted
full-match goal rates (lam, mu) on the current score and elapsed time,
instead of requiring a separate live-specific model class.

Validated offline (scripts/experiment_inplay_dixon_coles.py,
2026-09-30): beats the static pre-match probability at every checkpoint
for EPL/SERIE_A/LA_LIGA (La Liga confirmed clean after fixing the
shots-table dedup bug, migration 0037). Deliberately excludes
Dixon-Coles' low-score correction (rho) -- an ablation showed it
changes results in the 4th decimal place (noise), and rho was fit for
a full 90' match, not this shortened remaining-time window.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import poisson

MAX_GOALS = 10


def inplay_win_probs(lam: float, mu: float, h_now: int, a_now: int,
                     minute: int) -> tuple[float, float, float]:
    """
    (home_win, draw, away_win) conditioned on the current score at
    `minute`. Scales the remaining-time goal expectation by the
    fraction of the match left, builds a small scoreline matrix for
    ADDITIONAL goals only, then combines with the already-banked
    h_now/a_now lead -- the exact same fitted lam/mu the pre-match
    slate used for this fixture, no separate live model.
    """
    remaining = max(90 - minute, 1) / 90.0
    lam_r, mu_r = lam * remaining, mu * remaining
    hp = poisson.pmf(np.arange(MAX_GOALS + 1), lam_r)
    ap = poisson.pmf(np.arange(MAX_GOALS + 1), mu_r)
    m = np.outer(hp, ap)
    m = m / m.sum()
    i, j = np.indices(m.shape)
    final_h, final_a = h_now + i, a_now + j
    return (float(m[final_h > final_a].sum()),
           float(m[final_h == final_a].sum()),
           float(m[final_h < final_a].sum()))
