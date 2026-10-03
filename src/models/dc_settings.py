"""
Dixon-Coles fit settings shared by every production fit: the slate
generator, the final pass, the live in-play poller (all via
generate_slate.fit_dixon_coles) and compute_team_ratings.py, which must
match the live model.

reg for full leagues (ADR-014): 0.0 -> 0.25. With reg=0, a team with
zero goals scored (or conceded) in its fit window has an unbounded MLE
rating -- live, promoted Coventry was priced at a 5e-8 win probability
(degenerate_prediction_skips, Sep 2026). scripts/experiment_dc_ridge.py:
on 2025-26 holdouts reg=0.25 lifted the lowest stated probability from
~3e-7 to ~3% in EPL/La Liga/MLS and cut the worst log loss from 14.9 /
13.8 to 3.3 / 2.5, while RPS moved -0.0001 to -0.0005 (no cost). It was
fixed in advance as the smallest tested reg that cost nothing on the
2024-25 tune season, which itself had no blowups to tune against.
"""
from __future__ import annotations

SMALL_SAMPLE_MATCHES = 200


def dc_fit_settings(n_matches: int) -> tuple[float, float]:
    """(xi, reg) for a Dixon-Coles fit on n_matches."""
    if n_matches < SMALL_SAMPLE_MATCHES:
        return 0.0005, 8.0
    return 0.0015, 0.25
