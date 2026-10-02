"""
poll_live_winprob.py fetches /fixtures/events once per live fixture per
tick: the same response decides the red-card side AND is stored in
match_events (the in-play chart's goal/card markers need it; before
2026-10-02 it was discarded and match_events only came from a manual
backfill).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

from poll_live_winprob import red_card_side  # noqa: E402

HOME, AWAY = 1600, 1601


def _card(team_id, detail):
    return {"type": "Card", "detail": detail, "team": {"id": team_id}, "time": {"elapsed": 30}}


def test_no_events_means_no_red_card():
    assert red_card_side([], HOME) is None


def test_yellow_cards_are_not_red():
    assert red_card_side([_card(HOME, "Yellow Card")], HOME) is None


def test_home_red_card():
    assert red_card_side([_card(HOME, "Red Card")], HOME) is True


def test_away_red_card():
    assert red_card_side([_card(AWAY, "Red Card")], HOME) is False
