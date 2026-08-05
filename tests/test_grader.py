"""
Unit tests for the grading engine.

grade_prediction() is a pure function over dicts, so these need no database.
The grading semantics documented in grader.py's docstring are the spec:
  - half-lines make pushes impossible; integer lines that land exactly are void
  - 1X2 grades against the 90-minute result
  - postponed/abandoned matches are void
"""
from grading.grader import _grade_line, grade_prediction

FINAL = {"status": "final", "home_goals": 2, "away_goals": 1}


def pred(market, side, line=None):
    return {"market": market, "side": side, "line": line}


# ---------- 1X2 ----------

def test_1x2_home_win_hits_on_home():
    assert grade_prediction(pred("1X2", "home"), FINAL, {}) == ("hit", 1.0)


def test_1x2_home_win_misses_on_away_and_draw():
    assert grade_prediction(pred("1X2", "away"), FINAL, {})[0] == "miss"
    assert grade_prediction(pred("1X2", "draw"), FINAL, {})[0] == "miss"


def test_1x2_draw():
    match = {"status": "final", "home_goals": 1, "away_goals": 1}
    assert grade_prediction(pred("1X2", "draw"), match, {}) == ("hit", 0.0)
    assert grade_prediction(pred("1X2", "home"), match, {})[0] == "miss"


def test_1x2_away_win():
    match = {"status": "final", "home_goals": 0, "away_goals": 3}
    assert grade_prediction(pred("1X2", "away"), match, {}) == ("hit", -3.0)


def test_1x2_actual_value_is_goal_difference():
    _, actual = grade_prediction(pred("1X2", "home"), FINAL, {})
    assert actual == FINAL["home_goals"] - FINAL["away_goals"]


# ---------- BTTS ----------

def test_btts_yes_hits_when_both_score():
    assert grade_prediction(pred("BTTS", "yes"), FINAL, {}) == ("hit", 1.0)


def test_btts_no_hits_on_clean_sheet():
    match = {"status": "final", "home_goals": 3, "away_goals": 0}
    assert grade_prediction(pred("BTTS", "no"), match, {}) == ("hit", 0.0)
    assert grade_prediction(pred("BTTS", "yes"), match, {})[0] == "miss"


def test_btts_no_hits_on_goalless_draw():
    match = {"status": "final", "home_goals": 0, "away_goals": 0}
    assert grade_prediction(pred("BTTS", "no"), match, {})[0] == "hit"


# ---------- TOTAL_GOALS ----------

def test_total_goals_over_half_line():
    # 2-1 = 3 goals
    assert grade_prediction(pred("TOTAL_GOALS", "over", 2.5), FINAL, {}) == ("hit", 3.0)
    assert grade_prediction(pred("TOTAL_GOALS", "under", 2.5), FINAL, {})[0] == "miss"


def test_total_goals_under_half_line():
    assert grade_prediction(pred("TOTAL_GOALS", "under", 3.5), FINAL, {}) == ("hit", 3.0)
    assert grade_prediction(pred("TOTAL_GOALS", "over", 3.5), FINAL, {})[0] == "miss"


def test_total_goals_integer_line_landing_exactly_is_void():
    outcome, actual = grade_prediction(pred("TOTAL_GOALS", "over", 3), FINAL, {})
    assert outcome == "void"
    assert actual == 3.0


# ---------- non-final matches ----------

def test_postponed_and_abandoned_are_void():
    for status in ("postponed", "abandoned", "scheduled", "live"):
        match = {"status": status, "home_goals": None, "away_goals": None}
        assert grade_prediction(pred("1X2", "home"), match, {}) == ("void", None)


def test_status_check_precedes_market_dispatch():
    """A postponed match voids even for markets that would otherwise read stats."""
    match = {"status": "postponed", "home_goals": None, "away_goals": None}
    assert grade_prediction(pred("CORNERS", "over", 4.5), match, {"actual": 9}) == ("void", None)


# ---------- count markets (caller supplies the observed value) ----------

def test_count_market_uses_supplied_actual():
    assert grade_prediction(pred("CORNERS", "over", 4.5), FINAL, {"actual": 7}) == ("hit", 7.0)
    assert grade_prediction(pred("CORNERS", "under", 4.5), FINAL, {"actual": 7})[0] == "miss"


def test_count_market_without_stats_is_void():
    """auto_grade skips these, but grade_prediction must not invent a result."""
    assert grade_prediction(pred("PLAYER_SAVES", "over", 3.5), FINAL, {}) == ("void", None)
    assert grade_prediction(pred("PLAYER_SAVES", "over", 3.5), FINAL, {"actual": None}) == ("void", None)


def test_player_goals_anytime_scorer_line():
    assert grade_prediction(pred("PLAYER_GOALS", "over", 0.5), FINAL, {"actual": 1})[0] == "hit"
    assert grade_prediction(pred("PLAYER_GOALS", "over", 0.5), FINAL, {"actual": 0})[0] == "miss"


# ---------- _grade_line invariants ----------

def test_half_lines_never_push():
    """The stated reason half-lines are used. Exhaustive over a realistic range."""
    for line in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5):
        for actual in range(0, 15):
            for side in ("over", "under"):
                outcome, _ = _grade_line(actual, line, side)
                assert outcome in ("hit", "miss"), (actual, line, side)


def test_over_and_under_are_always_complementary():
    for line in (2.5, 4.5, 5.5):
        for actual in range(0, 12):
            over, _ = _grade_line(actual, line, "over")
            under, _ = _grade_line(actual, line, "under")
            assert {over, under} == {"hit", "miss"}, (actual, line)


def test_integer_line_exact_match_is_void_both_sides():
    assert _grade_line(5, 5, "over") == ("void", 5.0)
    assert _grade_line(5, 5, "under") == ("void", 5.0)
