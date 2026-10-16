"""
Unit tests for the pure (non-DB, non-network) parts of NFL player props
-- prob_over() and candidate_lines(). rolling_yardage_stats() needs a
real DB cursor and current_depth_chart() needs a real nfl_data_py call;
both are exercised indirectly via generate_nfl_slate.py, same pattern
as this project's other DB/network-gated ingestion functions.
"""

from models.nfl_player_props import (candidate_lines, depth_roster_disagreement, prob_over,
                                     reserved_players)


def test_prob_over_is_higher_for_a_lower_line():
    high = prob_over(avg_yards=250.0, sigma=45.0, line=180.0)
    low = prob_over(avg_yards=250.0, sigma=45.0, line=320.0)
    assert high > low
    assert 0.0 <= low <= high <= 1.0


def test_candidate_lines_are_never_whole_numbers():
    for line in candidate_lines(avg_yards=75.5, sigma=25.0):
        assert line == round(line * 2) / 2
        assert line != round(line)


def test_candidate_lines_scale_with_sigma():
    tight = candidate_lines(avg_yards=200.0, sigma=15.0)
    wide = candidate_lines(avg_yards=200.0, sigma=50.0)
    assert max(wide) - min(wide) > max(tight) - min(tight)


def test_candidate_lines_never_negative():
    for line in candidate_lines(avg_yards=10.0, sigma=40.0):
        assert line > 0


def test_candidate_lines_bracket_the_average():
    lines = candidate_lines(avg_yards=220.0, sigma=45.0)
    assert any(line < 220.0 for line in lines)
    assert any(line > 220.0 for line in lines)


# --- roster-status gate (ADR-012 follow-up) --------------------------------


def test_reserved_players_keeps_only_reserve_list_statuses():
    roster = {
        "00-ACHANE": ("RES", "R01"),
        "00-PUP": ("RES", "R04"),
        "00-ACTIVE": ("ACT", "A01"),
        "00-PRACTSQ": ("DEV", "E01"),
    }
    assert reserved_players(roster) == {
        "00-ACHANE": "on Reserve/Injured (IR)",
        "00-PUP": "on Reserve/Physically Unable to Perform (PUP)",
    }


def test_reserved_players_empty_roster_is_empty():
    assert reserved_players({}) == {}


def test_disagreement_lists_depth_chart_players_on_reserve():
    depth = {("MIA", "RB"): ["00-ACHANE", "00-OTHER"], ("BUF", "QB"): ["00-ALLEN"]}
    reserved = {"00-ACHANE": "on Reserve/Injured (IR)"}
    assert depth_roster_disagreement(depth, reserved) == [("MIA", "RB", "00-ACHANE")]


def test_disagreement_is_empty_when_chart_and_roster_agree():
    depth = {("BUF", "QB"): ["00-ALLEN"]}
    assert depth_roster_disagreement(depth, {"00-ELSEWHERE": "on Reserve/Injured (IR)"}) == []
