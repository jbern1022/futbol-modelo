"""
Unit tests for the core soccer grading markets: 1X2, BTTS, TOTAL_GOALS,
and count markets (CORNERS/SOT). The NFL/NBA markets (SPREAD, MONEYLINE,
TOTAL_POINTS) are covered separately in test_grader_nfl_nba_markets.py.
"""
from grading.grader import grade_prediction


def _match(home_score, away_score, status="final"):
    return {"status": status, "home_score": home_score, "away_score": away_score}


# ---------- 1X2 ----------

def test_1x2_home_win():
    pred = {"market": "1X2", "side": "home", "line": None}
    outcome, actual = grade_prediction(pred, _match(2, 0), {})
    assert outcome == "hit"
    assert actual == 2.0


def test_1x2_away_win():
    pred = {"market": "1X2", "side": "away", "line": None}
    outcome, actual = grade_prediction(pred, _match(0, 1), {})
    assert outcome == "hit"
    assert actual == -1.0


def test_1x2_draw():
    pred = {"market": "1X2", "side": "draw", "line": None}
    outcome, actual = grade_prediction(pred, _match(1, 1), {})
    assert outcome == "hit"
    assert actual == 0.0


def test_1x2_wrong_side_misses():
    pred = {"market": "1X2", "side": "home", "line": None}
    outcome, actual = grade_prediction(pred, _match(0, 2), {})
    assert outcome == "miss"
    assert actual == -2.0


def test_1x2_non_final_voids():
    pred = {"market": "1X2", "side": "home", "line": None}
    outcome, actual = grade_prediction(pred, _match(2, 0, status="postponed"), {})
    assert outcome == "void"
    assert actual is None


# ---------- BTTS ----------

def test_btts_yes_hit():
    pred = {"market": "BTTS", "side": "yes", "line": None}
    outcome, actual = grade_prediction(pred, _match(1, 1), {})
    assert outcome == "hit"
    assert actual == 1.0


def test_btts_yes_miss_clean_sheet():
    pred = {"market": "BTTS", "side": "yes", "line": None}
    outcome, actual = grade_prediction(pred, _match(2, 0), {})
    assert outcome == "miss"
    assert actual == 0.0


def test_btts_no_hit_clean_sheet():
    pred = {"market": "BTTS", "side": "no", "line": None}
    outcome, actual = grade_prediction(pred, _match(3, 0), {})
    assert outcome == "hit"
    assert actual == 0.0


def test_btts_no_miss_both_scored():
    pred = {"market": "BTTS", "side": "no", "line": None}
    outcome, actual = grade_prediction(pred, _match(2, 1), {})
    assert outcome == "miss"
    assert actual == 1.0


# ---------- TOTAL_GOALS ----------

def test_total_goals_over_hit():
    pred = {"market": "TOTAL_GOALS", "side": "over", "line": 2.5}
    outcome, actual = grade_prediction(pred, _match(2, 1), {})
    assert outcome == "hit"
    assert actual == 3.0


def test_total_goals_over_miss():
    pred = {"market": "TOTAL_GOALS", "side": "over", "line": 2.5}
    outcome, actual = grade_prediction(pred, _match(1, 1), {})
    assert outcome == "miss"
    assert actual == 2.0


def test_total_goals_under_hit():
    pred = {"market": "TOTAL_GOALS", "side": "under", "line": 2.5}
    outcome, actual = grade_prediction(pred, _match(1, 0), {})
    assert outcome == "hit"
    assert actual == 1.0


def test_total_goals_integer_line_push_voids():
    # Integer line: total == line is a push
    pred = {"market": "TOTAL_GOALS", "side": "over", "line": 3.0}
    outcome, actual = grade_prediction(pred, _match(2, 1), {})
    assert outcome == "void"
    assert actual == 3.0


# ---------- Count markets (CORNERS / SOT) ----------

def test_corners_over_hit():
    pred = {"market": "CORNERS", "side": "over", "line": 4.5}
    outcome, actual = grade_prediction(pred, _match(1, 1), {"actual": 6.0})
    assert outcome == "hit"
    assert actual == 6.0


def test_corners_over_miss():
    pred = {"market": "CORNERS", "side": "over", "line": 4.5}
    outcome, actual = grade_prediction(pred, _match(1, 1), {"actual": 3.0})
    assert outcome == "miss"
    assert actual == 3.0


def test_sot_missing_stats_voids():
    # If stats haven't arrived yet, grade should void rather than crash
    pred = {"market": "SOT", "side": "over", "line": 3.5}
    outcome, actual = grade_prediction(pred, _match(1, 0), {})
    assert outcome == "void"
    assert actual is None
