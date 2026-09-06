"""
Unit tests for the pure (non-DB, non-network) parts of NFL player props
-- prob_over() and candidate_lines(). rolling_yardage_stats() needs a
real DB cursor and current_depth_chart() needs a real nfl_data_py call;
both are exercised indirectly via generate_nfl_slate.py, same pattern
as this project's other DB/network-gated ingestion functions.
"""
import pytest

from models.nfl_player_props import candidate_lines, prob_over


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
