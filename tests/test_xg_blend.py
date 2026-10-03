"""
Goals + xG blend (ADR-016). Ratings fit to xG are blended 50/50 with the
goals fit on the log-rate scale; promoted after the pre-registered La
Liga test (scripts/experiment_xg_blend.py --fixed-w 0.5: pooled RPS
-0.0026, 95% CI [-0.0037, -0.0014] over 1,514 matches).
"""
import numpy as np
import pandas as pd
import pytest

from dixon_coles import DixonColes, derive_markets
from models.xg_blend import BlendedDixonColes, XgRatings


def _league(seed=3, n_teams=8, rounds=4):
    rng = np.random.default_rng(seed)
    teams = [f"T{i}" for i in range(n_teams)]
    rows, day = [], pd.Timestamp("2025-08-01")
    for _ in range(rounds):
        for i, h in enumerate(teams):
            for a in teams[i + 1:]:
                hx, ax = rng.gamma(4, 0.38), rng.gamma(4, 0.30)
                rows.append({"date": day, "home": h, "away": a, "hg": int(rng.poisson(hx)),
                             "ag": int(rng.poisson(ax)), "hxg": hx, "axg": ax})
                day += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def test_rates_are_the_log_scale_blend_of_both_fits():
    df = _league()
    goals = DixonColes(xi=0.0015).fit(df[["date", "home", "away", "hg", "ag"]], reg=0.25)
    xg = XgRatings().fit(df, xi=0.0015, reg=0.25)
    blended = BlendedDixonColes(goals, xg, weight=0.5)
    lam_g, mu_g, rho = goals.rates("T1", "T2")
    llam_x, lmu_x = xg.log_rates("T1", "T2")
    lam, mu, rho_b = blended.rates("T1", "T2")
    assert lam == pytest.approx(np.exp(0.5 * np.log(lam_g) + 0.5 * llam_x))
    assert mu == pytest.approx(np.exp(0.5 * np.log(mu_g) + 0.5 * lmu_x))
    assert rho_b == rho


def test_predict_is_a_proper_distribution_and_teams_match_the_goals_fit():
    df = _league()
    blended = BlendedDixonColes.fit(df, xi=0.0015, reg=0.25, weight=0.5)
    mk = derive_markets(blended.predict("T0", "T5"))
    assert mk["home_win"] + mk["draw"] + mk["away_win"] == pytest.approx(1.0)
    assert set(blended.teams) == set(df.home) | set(df.away)


def test_team_without_xg_falls_back_to_goals_rates():
    df = _league()
    df.loc[(df.home == "T7") | (df.away == "T7"), ["hxg", "axg"]] = np.nan
    blended = BlendedDixonColes.fit(df, xi=0.0015, reg=0.25, weight=0.5)
    assert blended.rates("T7", "T1") == pytest.approx(blended.goals.rates("T7", "T1"))
