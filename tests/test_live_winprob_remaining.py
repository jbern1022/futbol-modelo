"""
Remaining-time rule for in-play win probability (ADR-013).

Real case (2026-10-02): MLS match 4606, 1-1 in stoppage time, API-Football
elapsed capped at 90 -- the linear rule left 1 minute of goal expectation
and put the draw at 0.966; the home side then scored. Across EPL/SERIE_A,
6.2% of goals come after minute 90, and the linear rule allows 1.1%.
"""
import pytest

from predictions.live_winprob import (REMAINING_GOAL_SHARE, inplay_win_probs,
                                      remaining_share)


def test_curve_covers_every_elapsed_minute_and_never_increases():
    assert len(REMAINING_GOAL_SHARE) == 91
    assert all(a >= b for a, b in zip(REMAINING_GOAL_SHARE, REMAINING_GOAL_SHARE[1:]))


def test_stoppage_time_keeps_real_goal_expectation_in_every_live_league():
    for league in ("EPL", "SERIE_A", "LA_LIGA", "MLS"):
        assert remaining_share(90, league) == pytest.approx(0.0618)
        assert remaining_share(90, league) > 5 * remaining_share(90, None)


def test_unspecified_league_keeps_the_linear_rule():
    assert remaining_share(60, None) == pytest.approx(30 / 90)
    assert remaining_share(90, None) == pytest.approx(1 / 90)


def test_elapsed_past_90_is_clamped():
    assert remaining_share(95, "EPL") == remaining_share(90, "EPL")


def test_level_score_in_stoppage_is_no_longer_a_near_certain_draw():
    lam, mu = 1.5, 1.2
    _, draw_linear, _ = inplay_win_probs(lam, mu, 1, 1, 90)
    _, draw_curve, _ = inplay_win_probs(lam, mu, 1, 1, 90, league="EPL")
    assert draw_linear > 0.96
    assert 0.80 < draw_curve < 0.88


def test_every_live_league_has_a_red_card_factor_in_the_right_direction():
    from predictions.live_winprob import RED_CARD_FACTORS, apply_red_card
    for league in ("EPL", "SERIE_A", "MLS", "LA_LIGA"):
        down, up = RED_CARD_FACTORS[league]
        assert down < 1 < up
        assert apply_red_card(1.5, 1.2, league, home_is_down=True) == pytest.approx((1.5 * down, 1.2 * up))
    assert apply_red_card(1.5, 1.2, "WC", home_is_down=True) == (1.5, 1.2)
