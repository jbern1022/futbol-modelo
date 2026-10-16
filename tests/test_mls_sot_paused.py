"""
MLS shots on target are paused (Todoist 6hmV8gr2VhFrWGh7). The pooled props model is
trained without MLS (MLS has no xG, so every MLS row is dropped as incomplete) but
used to score MLS with xG missing; it under-predicted MLS SOT by 11% to 16%.
Pausing means MLS leaves the SOT league set only: CORNERS and every other league
are untouched, and the set that defines the training pool loses no row it had.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

from generate_slate import PROPS_LEAGUES, PROPS_MARKETS  # noqa: E402


def test_mls_is_not_scored_for_shots_on_target():
    assert "MLS" not in PROPS_MARKETS["SOT"]["leagues"]


def test_the_other_soccer_leagues_still_get_shots_on_target():
    assert {"EPL", "SERIE_A", "LA_LIGA"} <= PROPS_MARKETS["SOT"]["leagues"]


def test_corners_and_player_props_are_unchanged_for_mls():
    assert "MLS" in PROPS_MARKETS["CORNERS"]["leagues"]
    assert "MLS" in PROPS_LEAGUES


def test_the_props_gate_still_admits_mls_so_corners_keep_running():
    assert any("MLS" in spec["leagues"] for spec in PROPS_MARKETS.values())
