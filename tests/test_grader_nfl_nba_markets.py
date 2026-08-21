"""
Unit tests for the SPREAD/MONEYLINE/TOTAL_POINTS grading paths added to
grader.py for the eventual NFL/NBA build. Hand-checked cases against
standard sports-betting conventions -- these markets have no live
predictions yet, so there's no production data to cross-check against;
correctness here rests entirely on getting the signed-margin arithmetic
right by inspection.
"""
from grading.grader import grade_prediction


def _match(home_score, away_score, status="final"):
    return {"status": status, "home_score": home_score, "away_score": away_score}


def test_spread_home_favorite_covers():
    # Home favored by 3.5 (line=-3.5), wins by 7 -> covers.
    pred = {"market": "SPREAD", "side": "home", "line": -3.5}
    outcome, actual = grade_prediction(pred, _match(24, 17), {})
    assert outcome == "hit"
    assert actual == 7.0


def test_spread_home_favorite_fails_to_cover():
    # Home favored by 3.5, wins by only 2 -> doesn't cover, even though
    # they won the game outright.
    pred = {"market": "SPREAD", "side": "home", "line": -3.5}
    outcome, actual = grade_prediction(pred, _match(20, 18), {})
    assert outcome == "miss"
    assert actual == 2.0


def test_spread_away_underdog_covers_by_losing_close():
    # Away getting 3.5 (line=+3.5), loses by 2 -> covers (kept it within
    # the spread) even though they lost the game outright.
    pred = {"market": "SPREAD", "side": "away", "line": 3.5}
    outcome, actual = grade_prediction(pred, _match(20, 18), {})
    assert outcome == "hit"
    assert actual == -2.0


def test_spread_exact_push_voids():
    # Home favored by exactly 3, wins by exactly 3 -> push, not a hit.
    pred = {"market": "SPREAD", "side": "home", "line": -3.0}
    outcome, actual = grade_prediction(pred, _match(23, 20), {})
    assert outcome == "void"
    assert actual == 3.0


def test_moneyline_home_win():
    pred = {"market": "MONEYLINE", "side": "home", "line": None}
    outcome, actual = grade_prediction(pred, _match(24, 17), {})
    assert outcome == "hit"


def test_moneyline_away_pick_on_home_win_misses():
    pred = {"market": "MONEYLINE", "side": "away", "line": None}
    outcome, actual = grade_prediction(pred, _match(24, 17), {})
    assert outcome == "miss"


def test_moneyline_tie_voids():
    # Shouldn't happen in real NFL/NBA (both resolve ties in-game), but
    # the grader shouldn't guess a winner if it ever sees one.
    pred = {"market": "MONEYLINE", "side": "home", "line": None}
    outcome, actual = grade_prediction(pred, _match(20, 20), {})
    assert outcome == "void"


def test_total_points_over_and_under():
    over_pred = {"market": "TOTAL_POINTS", "side": "over", "line": 44.5}
    under_pred = {"market": "TOTAL_POINTS", "side": "under", "line": 44.5}
    match = _match(24, 21)  # total = 45

    outcome, actual = grade_prediction(over_pred, match, {})
    assert outcome == "hit" and actual == 45.0

    outcome, actual = grade_prediction(under_pred, match, {})
    assert outcome == "miss"
