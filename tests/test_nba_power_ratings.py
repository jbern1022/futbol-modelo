"""
Unit tests for the NBA total-points power-ratings model. Synthetic
score data, no network dependency -- matches test_nfl_power_ratings.py.
"""
import pandas as pd
import pytest

from models.nba_power_ratings import NBAPowerRatings


def _synthetic_games() -> pd.DataFrame:
    games = []
    teams = ["HIGH_SCORING", "LOW_SCORING", "MID1", "MID2", "MID3"]
    for home in teams:
        for away in teams:
            if home == away:
                continue
            base = 110
            bump = 15 if home == "HIGH_SCORING" or away == "HIGH_SCORING" else 0
            drop = 12 if home == "LOW_SCORING" or away == "LOW_SCORING" else 0
            hg = base + bump - drop
            ag = base + bump - drop - 3
            games.append({"home": home, "away": away, "home_score": hg, "away_score": ag})
    return pd.DataFrame(games)


def test_fit_ranks_high_scoring_team_above_low_scoring_team():
    model = NBAPowerRatings(alpha=1.0).fit(_synthetic_games())
    assert model.total_ratings["HIGH_SCORING"] > model.total_ratings["MID1"]
    assert model.total_ratings["MID1"] > model.total_ratings["LOW_SCORING"]


def test_predicted_total_reflects_both_teams():
    model = NBAPowerRatings(alpha=1.0).fit(_synthetic_games())
    high_game = model.predicted_total("HIGH_SCORING", "MID1")
    low_game = model.predicted_total("LOW_SCORING", "MID1")
    assert high_game > low_game


def test_candidate_lines_are_never_whole_numbers():
    model = NBAPowerRatings(alpha=1.0).fit(_synthetic_games())
    for home in model.teams:
        for away in model.teams:
            if home == away:
                continue
            for line in model.candidate_lines(home, away):
                assert line == round(line * 2) / 2  # a valid half-point
                assert line != round(line)  # never a whole number (no push)


def test_lower_candidate_lines_have_higher_prob_over():
    # A line well below the prediction should be very likely to clear;
    # one well above should be very unlikely to -- candidate_lines()'
    # offsets must actually translate into a monotonic confidence spread,
    # not all cluster near 0.5 the way a single at-the-median line would.
    model = NBAPowerRatings(alpha=1.0).fit(_synthetic_games())
    lines = model.candidate_lines("MID1", "MID2")
    probs = [model.prob_over("MID1", "MID2", line) for line in lines]
    assert probs == sorted(probs, reverse=True)
    assert probs[0] > 0.9   # lowest line (prediction - 6)
    assert probs[-1] < 0.1  # highest line (prediction + 6)


def test_fit_requires_completed_games():
    empty = pd.DataFrame(columns=["home", "away", "home_score", "away_score"])
    with pytest.raises(ValueError):
        NBAPowerRatings().fit(empty)


def test_unknown_team_falls_back_to_average_rating():
    model = NBAPowerRatings(alpha=1.0).fit(_synthetic_games())
    pred = model.predicted_total("MID1", "NEW_EXPANSION_TEAM")
    assert pred == pytest.approx(model.total_ratings["MID1"] + model.total_intercept)
