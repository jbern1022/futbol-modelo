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

Remaining time (ADR-013): EPL/SERIE_A/LA_LIGA use an empirical
remaining-goal share by elapsed minute instead of (90 - minute) / 90,
which treated all of stoppage time as 1 minute.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import poisson

MAX_GOALS = 10

# Share of a match's goals scored AFTER each elapsed minute 0..90
# (ADR-013, scripts/experiment_inplay_stoppage.py, 2026-10-02). Pooled
# from 10,160 EPL + SERIE_A Understat goals, 2021-22 to 2025-26. Index 90
# is what's left once API-Football's status.elapsed caps at 90 for all of
# stoppage time. Holdout 2025-26, 89' log loss vs the linear rule:
# EPL 0.758 -> 0.513, SERIE_A 0.492 -> 0.352, LA_LIGA (never in the
# curve, so an out-of-league test) 0.476 -> 0.341; within +-0.001 before
# 60'. MLS (532-match 2025 holdout via match_events, also never in the
# curve) 0.611 -> 0.423. An earlier MLS run that "favored linear" scored
# only 33 matches -- all goalless games with no event data -- and was
# a sampling artifact (corrected 2026-10-02 after the 2025 backfill).
REMAINING_GOAL_SHARE = (
    0.9951, 0.9879, 0.9803, 0.9725, 0.9624, 0.9522, 0.9430, 0.9358, 0.9269, 0.9187,  # 0-9
    0.9091, 0.9002, 0.8901, 0.8796, 0.8707, 0.8626, 0.8521, 0.8419, 0.8319, 0.8232,  # 10-19
    0.8144, 0.8052, 0.7973, 0.7883, 0.7791, 0.7705, 0.7618, 0.7526, 0.7437, 0.7344,  # 20-29
    0.7232, 0.7121, 0.7035, 0.6938, 0.6833, 0.6726, 0.6615, 0.6515, 0.6435, 0.6333,  # 30-39
    0.6244, 0.6145, 0.6048, 0.5946, 0.5860, 0.5719, 0.5539, 0.5398, 0.5247, 0.5127,  # 40-49
    0.4996, 0.4888, 0.4782, 0.4652, 0.4537, 0.4406, 0.4296, 0.4183, 0.4076, 0.3969,  # 50-59
    0.3844, 0.3733, 0.3635, 0.3513, 0.3393, 0.3272, 0.3174, 0.3072, 0.2948, 0.2833,  # 60-69
    0.2730, 0.2628, 0.2526, 0.2422, 0.2317, 0.2195, 0.2087, 0.1978, 0.1877, 0.1784,  # 70-79
    0.1685, 0.1577, 0.1463, 0.1349, 0.1252, 0.1148, 0.1040, 0.0934, 0.0828, 0.0723,  # 80-89
    0.0618,  # 90 (all of stoppage time)
)
EMPIRICAL_REMAINING_LEAGUES = frozenset({"EPL", "SERIE_A", "LA_LIGA", "MLS"})


def remaining_share(minute: int, league: str | None = None) -> float:
    """Fraction of a full match's expected goals still to come at
    `minute` elapsed. league=None (or any league outside
    EMPIRICAL_REMAINING_LEAGUES) keeps the original linear rule."""
    if league in EMPIRICAL_REMAINING_LEAGUES:
        return REMAINING_GOAL_SHARE[min(max(minute, 0), 90)]
    return max(90 - minute, 1) / 90.0

# Empirical red-card multipliers (scripts/experiment_redcard_calibration.py,
# 2026-09-30): for each league, (down_factor, up_factor) applied to the
# sent-off team's and their opponent's remaining-time goal rate from the
# red-card minute onward. Derived from real EPL/SERIE_A matches with a
# single red card between minute 10-80 (145/149 usable matches
# respectively), comparing ACTUAL remaining-time goals (futbol.shots)
# against Dixon-Coles' unadjusted expectation for that same window.
# In-sample RPS improvement when applied: EPL +16.0%, SERIE_A +29.3% --
# real, but in-sample only (not yet validated on a held-out red-card
# set), see the calibration script's own printed caveat. No entry yet
# for LA_LIGA -- default (1.0, 1.0) applies until it is
# calibrated the same way.
#
# Recalibrated 2026-10-02 (ADR-013) against remaining_share() instead of
# the linear rule. The old factors, (0.475, 1.551) and (0.584, 1.850),
# had absorbed the stoppage-time goals the linear expectation left out;
# keeping them alongside the new curve would count those goals twice.
#
# MLS (2026-10-03, scripts/experiment_redcard_calibration_mls.py): from
# match_events, no API calls. 79 single-red matches across 2025+2026.
# Unlike EPL/SERIE_A this one is OUT-OF-SAMPLE: each season scored with
# factors calibrated on the other gave RPS +20.4% at the red-card minute,
# 95% CI [-0.064, -0.005] on the paired difference. Shipped factors are
# pooled over both seasons. Under the ~100-match bar, but cross-validated
# both ways and the same direction as EPL/SERIE_A.
RED_CARD_FACTORS = {
    "EPL": (0.419, 1.370),
    "SERIE_A": (0.513, 1.629),
    "MLS": (0.488, 1.579),
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
                     minute: int, league: str | None = None) -> tuple[float, float, float]:
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
    remaining = remaining_share(minute, league)
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
