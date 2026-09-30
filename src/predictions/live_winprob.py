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

# Empirical red-card multipliers (scripts/experiment_redcard_calibration.py,
# 2026-09-30): for each league, (down_factor, up_factor) applied to the
# sent-off team's and their opponent's remaining-time goal rate from the
# red-card minute onward. Derived from real EPL/SERIE_A matches with a
# single red card between minute 10-80 (145/149 usable matches
# respectively), comparing ACTUAL remaining-time goals (futbol.shots)
# against Dixon-Coles' unadjusted expectation for that same window.
# In-sample RPS improvement when applied: EPL +16.4%, SERIE_A +30.3% --
# real, but in-sample only (not yet validated on a held-out red-card
# set), see the calibration script's own printed caveat. No entry yet
# for MLS/LA_LIGA -- default (1.0, 1.0) applies until each is
# calibrated the same way.
RED_CARD_FACTORS = {
    "EPL": (0.475, 1.551),
    "SERIE_A": (0.584, 1.850),
}


def apply_red_card(lam: float, mu: float, league: str, home_is_down: bool | None) -> tuple[float, float]:
    """
    Applies RED_CARD_FACTORS to whichever of lam (home)/mu (away) is
    the sent-off team, the other gets the opponent (up) factor.
    home_is_down=None means no red card has happened -- returns
    lam/mu unchanged. Call this BEFORE inplay_win_probs, which stays
    a plain conditioning function with no red-card knowledge of its
    own.
    """
    if home_is_down is None:
        return lam, mu
    down_factor, up_factor = RED_CARD_FACTORS.get(league, (1.0, 1.0))
    if home_is_down:
        return lam * down_factor, mu * up_factor
    return lam * up_factor, mu * down_factor


def inplay_win_probs(lam: float, mu: float, h_now: int, a_now: int,
                     minute: int) -> tuple[float, float, float]:
    """
    (home_win, draw, away_win) conditioned on the current score at
    `minute`. Scales the remaining-time goal expectation by the
    fraction of the match left, builds a small scoreline matrix for
    ADDITIONAL goals only, then combines with the already-banked
    h_now/a_now lead -- the exact same fitted lam/mu the pre-match
    slate used for this fixture, no separate live model. Pass lam/mu
    already through apply_red_card() first if a red card applies --
    this function itself has no red-card awareness.
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
