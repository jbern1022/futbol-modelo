"""
Unit tests for the pure (non-DB) parts of NBA player points props --
prob_over() and candidate_lines(). rolling_points_stats() needs a real
DB cursor and is exercised indirectly via generate_nba_slate.py, same
pattern as this project's other DB-gated ingestion functions.
"""
import pytest

from models.nba_player_points import candidate_lines, prob_over


def test_prob_over_is_higher_for_a_lower_line():
    high = prob_over(avg_points=20.0, sigma=6.0, line=15.0)
    low = prob_over(avg_points=20.0, sigma=6.0, line=25.0)
    assert high > low
    assert 0.0 <= low <= high <= 1.0


def test_candidate_lines_are_never_whole_numbers():
    for line in candidate_lines(avg_points=22.5, sigma=7.0):
        assert line == round(line * 2) / 2
        assert line != round(line)


def test_candidate_lines_scale_with_sigma():
    # A high-variance player's lines should spread wider than a
    # low-variance player's, even with the same average -- confirms the
    # offsets are genuinely sigma-relative, not a fixed point value.
    tight = candidate_lines(avg_points=20.0, sigma=3.0)
    wide = candidate_lines(avg_points=20.0, sigma=9.0)
    assert max(wide) - min(wide) > max(tight) - min(tight)


def test_candidate_lines_never_negative():
    # A very low-scoring player with a large sigma could otherwise
    # produce a nonsensical negative points line.
    for line in candidate_lines(avg_points=2.0, sigma=8.0):
        assert line > 0


def test_candidate_lines_bracket_the_average():
    lines = candidate_lines(avg_points=20.0, sigma=6.0)
    assert any(line < 20.0 for line in lines)
    assert any(line > 20.0 for line in lines)
