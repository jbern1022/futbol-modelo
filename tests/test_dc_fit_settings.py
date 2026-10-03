"""
Production Dixon-Coles fit settings (ADR-014). With reg=0, a team with
zero goals in its fit window has an unbounded MLE attack rating: live,
2026-27 promoted Coventry got a 5e-8 win probability, and in the
2025-26 walk-forward one EPL and one La Liga match scored log loss
14.9 / 13.8. reg=0.25 bounded every case at ~3%+ at no RPS cost.
"""
import numpy as np
import pandas as pd

from dixon_coles import DixonColes, derive_markets
from models.dc_settings import dc_fit_settings


def _league_with_a_promoted_team_that_never_scored() -> pd.DataFrame:
    # Realistic, seeded Poisson scorelines: with only 2-1/1-1 results the
    # low-score correction rho has nothing to fit and runs off to -1e7,
    # which is a property of the fake data, not of the fix under test.
    rng = np.random.default_rng(7)
    teams = [f"T{i}" for i in range(10)]
    rows, day = [], pd.Timestamp("2025-08-01")
    for _ in range(4):
        for i, h in enumerate(teams):
            for a in teams[i + 1:]:
                rows.append({"date": day, "home": h, "away": a,
                             "hg": int(rng.poisson(1.5)), "ag": int(rng.poisson(1.15))})
                day += pd.Timedelta(days=1)
    # Promoted side: two games, no goals.
    rows.append({"date": day, "home": "Promoted", "away": "T0", "hg": 0, "ag": 2})
    rows.append({"date": day + pd.Timedelta(days=7), "home": "T1", "away": "Promoted", "hg": 3, "ag": 0})
    return pd.DataFrame(rows)


def test_full_league_settings_use_a_small_ridge():
    xi, reg = dc_fit_settings(1500)
    assert (xi, reg) == (0.0015, 0.25)


def test_small_samples_keep_the_heavier_ridge():
    assert dc_fit_settings(150) == (0.0005, 8.0)


def test_a_team_that_never_scored_is_not_priced_at_zero():
    df = _league_with_a_promoted_team_that_never_scored()
    xi, reg = dc_fit_settings(1500)
    mk = derive_markets(DixonColes(xi=xi).fit(df, reg=reg).predict("Promoted", "T2"))
    assert mk["home_win"] > 0.01

    unregularized = derive_markets(DixonColes(xi=xi).fit(df, reg=0.0).predict("Promoted", "T2"))
    assert unregularized["home_win"] < mk["home_win"] / 10
