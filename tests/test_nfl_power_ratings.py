"""
Unit tests for the NFL power-ratings model. Uses small synthetic score
data (not real nfl_data_py calls -- no network dependency) so these run
fast and offline, matching the rest of this project's model tests.
"""
import pandas as pd
import pytest

from models.nfl_power_ratings import NFLPowerRatings


def _synthetic_games() -> pd.DataFrame:
    # A strong home team, a weak away team, both playing everyone else
    # at a roughly even level -- enough games for ridge regression to
    # separate the two extremes from the pack.
    games = []
    teams = ["STRONG", "WEAK", "MID1", "MID2", "MID3"]
    for i, home in enumerate(teams):
        for away in teams:
            if home == away:
                continue
            base = 20
            if home == "STRONG":
                hg, ag = base + 14, base - 4
            elif away == "STRONG":
                hg, ag = base - 4, base + 14
            elif home == "WEAK":
                hg, ag = base - 10, base + 6
            elif away == "WEAK":
                hg, ag = base + 6, base - 10
            else:
                hg, ag = base, base
            games.append({"home": home, "away": away, "home_score": hg, "away_score": ag})
    return pd.DataFrame(games)


def test_fit_ranks_strong_team_above_weak_team():
    model = NFLPowerRatings(alpha=1.0).fit(_synthetic_games())
    assert model.margin_ratings["STRONG"] > model.margin_ratings["MID1"]
    assert model.margin_ratings["MID1"] > model.margin_ratings["WEAK"]


def test_prob_home_wins_favors_strong_team_at_home():
    model = NFLPowerRatings(alpha=1.0).fit(_synthetic_games())
    assert model.prob_home_wins("STRONG", "WEAK") > 0.9
    assert model.prob_home_wins("WEAK", "STRONG") < 0.1


def test_probabilities_are_valid():
    model = NFLPowerRatings(alpha=1.0).fit(_synthetic_games())
    p_win = model.prob_home_wins("MID1", "MID2")
    p_cover = model.prob_home_covers("MID1", "MID2", -3.0)
    p_over = model.prob_over("MID1", "MID2", 40.0)
    for p in (p_win, p_cover, p_over):
        assert 0.0 <= p <= 1.0


def test_bigger_favorite_covers_smaller_spread_more_often():
    model = NFLPowerRatings(alpha=1.0).fit(_synthetic_games())
    # STRONG at home should be more likely to cover a modest -3 than a
    # tougher -10 -- covering probability must fall as the line gets
    # harder to clear.
    easy = model.prob_home_covers("STRONG", "WEAK", -3.0)
    hard = model.prob_home_covers("STRONG", "WEAK", -20.0)
    assert easy > hard


def test_fit_requires_completed_games():
    empty = pd.DataFrame(columns=["home", "away", "home_score", "away_score"])
    with pytest.raises(ValueError):
        NFLPowerRatings().fit(empty)


def test_unknown_team_falls_back_to_average_rating():
    model = NFLPowerRatings(alpha=1.0).fit(_synthetic_games())
    # A team never seen in training defaults to rating 0.0 (league
    # average) rather than raising -- predict() must stay callable for
    # any team pairing the caller passes in.
    pred = model.predict("MID1", "NEW_EXPANSION_TEAM")
    assert pred["predicted_margin"] == pytest.approx(
        model.margin_ratings["MID1"] + model.home_field_advantage
    )
