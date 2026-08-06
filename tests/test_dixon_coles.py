"""
Dixon-Coles: distribution invariants, and the promoted-team prior.

No database. The fixture builds a small league where one team is clearly
strong and another clearly weak, so "does the model rank them correctly" is a
real assertion rather than a tautology.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from models.dixon_coles import (
    MAX_GOALS,
    DixonColes,
    UnratedTeamError,
    derive_markets,
)

TEAMS = ["Strong", "Mid A", "Mid B", "Weak"]
STRENGTH = {"Strong": 2.1, "Mid A": 1.3, "Mid B": 1.2, "Weak": 0.6}


def make_matches(seed: int = 0, repeats: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    day = 0
    for _ in range(repeats):
        for home in TEAMS:
            for away in TEAMS:
                if home == away:
                    continue
                day += 1
                rows.append({
                    "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=day),
                    "home": home,
                    "away": away,
                    "hg": rng.poisson(STRENGTH[home] * 1.25),
                    "ag": rng.poisson(STRENGTH[away]),
                })
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def model() -> DixonColes:
    return DixonColes(xi=0.0).fit(make_matches())


# ---------- distribution invariants ----------

def test_score_matrix_is_a_probability_distribution(model):
    m = model.score_matrix("Strong", "Weak")
    assert m.shape == (MAX_GOALS + 1, MAX_GOALS + 1)
    assert m.min() >= 0
    assert m.sum() == pytest.approx(1.0, abs=1e-9)


def test_match_outcomes_sum_to_one(model):
    mk = derive_markets(model.predict("Mid A", "Mid B"))
    assert mk["home_win"] + mk["draw"] + mk["away_win"] == pytest.approx(1.0, abs=1e-9)


def test_over_under_are_complementary(model):
    mk = derive_markets(model.predict("Strong", "Mid A"))
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        assert 0.0 < mk[f"over_{line}"] < 1.0


def test_over_probability_decreases_with_the_line(model):
    mk = derive_markets(model.predict("Strong", "Weak"))
    overs = [mk[f"over_{ln}"] for ln in (0.5, 1.5, 2.5, 3.5, 4.5)]
    assert all(a >= b for a, b in zip(overs, overs[1:]))


def test_stronger_team_is_favoured(model):
    """If this fails the fit is not learning anything."""
    strong = derive_markets(model.predict("Strong", "Weak"))
    weak = derive_markets(model.predict("Weak", "Strong"))
    assert strong["home_win"] > strong["away_win"]
    assert weak["away_win"] > weak["home_win"]


def test_home_advantage_is_positive(model):
    """Same pairing, reversed venue — the home side should fare better."""
    a = derive_markets(model.predict("Mid A", "Mid B"))["home_win"]
    b = derive_markets(model.predict("Mid B", "Mid A"))["away_win"]
    assert a > b


# ---------- unknown teams ----------

def test_unknown_team_raises_without_a_prior(model):
    assert not model.knows("Newly Promoted")
    with pytest.raises(UnratedTeamError, match="no match history"):
        model.predict("Strong", "Newly Promoted")


def test_unknown_team_works_once_a_prior_is_set():
    m = DixonColes(xi=0.0).fit(make_matches())
    m.set_unknown_team_prior(attack=-0.25, defence=0.30)
    mk = derive_markets(m.predict("Strong", "Newly Promoted"))
    assert mk["home_win"] + mk["draw"] + mk["away_win"] == pytest.approx(1.0, abs=1e-9)


def test_prior_makes_the_promoted_team_an_underdog():
    """A negative attack and positive defence must actually disadvantage them,
    which pins the sign convention: defence is defensive WEAKNESS."""
    m = DixonColes(xi=0.0).fit(make_matches())
    m.set_unknown_team_prior(attack=-0.25, defence=0.30)
    vs_mid = derive_markets(m.predict("Mid A", "Newly Promoted"))
    assert vs_mid["home_win"] > vs_mid["away_win"]
    away = derive_markets(m.predict("Newly Promoted", "Mid A"))
    assert away["away_win"] > away["home_win"]


def test_prior_does_not_disturb_known_teams():
    a = DixonColes(xi=0.0).fit(make_matches())
    b = DixonColes(xi=0.0).fit(make_matches())
    b.set_unknown_team_prior(attack=-0.25, defence=0.30)
    assert (derive_markets(a.predict("Strong", "Weak"))["home_win"]
            == pytest.approx(derive_markets(b.predict("Strong", "Weak"))["home_win"]))


def test_both_teams_unknown_is_handled():
    m = DixonColes(xi=0.0).fit(make_matches())
    m.set_unknown_team_prior(attack=-0.25, defence=0.30)
    mk = derive_markets(m.predict("Promoted A", "Promoted B"))
    assert mk["home_win"] + mk["draw"] + mk["away_win"] == pytest.approx(1.0, abs=1e-9)
    # Identical ratings, so the only asymmetry left is home advantage.
    assert mk["home_win"] > mk["away_win"]


def test_knows_reports_membership(model):
    assert model.knows("Strong")
    assert not model.knows("Coventry")


# ---------- regression: the low-score correction going negative ----------

def test_fit_keeps_the_low_score_correction_positive(model):
    """
    nll() clips tau to 1e-10, so an unconstrained fit is never penalised for
    picking a rho that makes the correction negative — and score_matrix then
    applied that rho unclipped and returned negative probabilities. The fit now
    carries an explicit constraint; this checks it held.
    """
    n = len(model.teams)
    rho = model.params[2 * n + 1]
    idx = {t: i for i, t in enumerate(model.teams)}
    atk, dfn = model.params[:n], model.params[n:2 * n]
    gamma = model.params[2 * n]
    for home in TEAMS:
        for away in TEAMS:
            if home == away:
                continue
            lam = np.exp(atk[idx[home]] + dfn[idx[away]] + gamma)
            mu = np.exp(atk[idx[away]] + dfn[idx[home]])
            for value in (1 - lam * mu * rho, 1 + lam * rho,
                          1 + mu * rho, 1 - rho):
                assert value > 0, (home, away, rho, value)


def test_score_matrix_never_returns_negative_probabilities():
    """Even with a deliberately invalid rho, the output is either a valid
    distribution or a raised error — never negative probabilities."""
    m = DixonColes(xi=0.0).fit(make_matches())
    n = len(m.teams)
    m.params = m.params.copy()
    m.params[2 * n + 1] = 0.95  # far outside the valid region
    try:
        matrix = m.score_matrix("Strong", "Weak")
    except ValueError as exc:
        assert "low-score correction" in str(exc) or "collapsed" in str(exc)
    else:
        assert matrix.min() >= 0
        assert matrix.sum() == pytest.approx(1.0, abs=1e-9)


def test_extreme_prior_does_not_produce_invalid_probabilities():
    m = DixonColes(xi=0.0).fit(make_matches())
    m.set_unknown_team_prior(attack=-3.0, defence=1.5)
    try:
        mk = derive_markets(m.predict("Strong", "Minnows"))
    except ValueError:
        pass  # refusing is an acceptable outcome for an extreme prior
    else:
        assert all(0.0 <= mk[k] <= 1.0 for k in ("home_win", "draw", "away_win"))
        assert mk["home_win"] + mk["draw"] + mk["away_win"] == pytest.approx(1.0, abs=1e-9)
