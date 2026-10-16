"""
Per-league API-Football xG scale (ADR-018). No database needed: a mock cursor
records which scale the UPDATE received.
"""
from unittest.mock import MagicMock

import pytest

from ingestion.api_football import (
    API_FOOTBALL_XG_SCALE, API_FOOTBALL_XG_SCALES, XG_FILL_LEAGUES, store_api_football_xg,
)
from models.xg_blend import XG_BLEND_LEAGUES


def test_each_fill_league_has_its_own_scale_and_bundesliga_is_lower():
    assert XG_FILL_LEAGUES == frozenset(API_FOOTBALL_XG_SCALES)
    for league in ("EPL", "SERIE_A", "LA_LIGA"):
        assert API_FOOTBALL_XG_SCALES[league] == API_FOOTBALL_XG_SCALE
    assert API_FOOTBALL_XG_SCALES["BUNDESLIGA"] == pytest.approx(1.095)


def test_every_blended_league_that_needs_api_xg_has_a_scale():
    assert XG_BLEND_LEAGUES <= XG_FILL_LEAGUES


def _update_params(cur):
    return [c.args[1] for c in cur.execute.call_args_list if c.args[0].lstrip().startswith("UPDATE")]


def test_bundesliga_xg_is_stored_with_its_own_scale_not_the_default():
    cur = MagicMock()
    store_api_football_xg(cur, "BUNDESLIGA", 1, 2, "2.00")
    assert _update_params(cur)[-1][0] == pytest.approx(2.00 * 1.095, abs=1e-3)


def test_epl_keeps_the_original_scale():
    cur = MagicMock()
    store_api_football_xg(cur, "EPL", 1, 2, "2.00")
    assert _update_params(cur)[-1][0] == pytest.approx(2.00 * 1.108, abs=1e-3)


def test_league_without_a_scale_is_not_filled():
    cur = MagicMock()
    store_api_football_xg(cur, "MLS", 1, 2, "2.00")
    assert _update_params(cur) == []
