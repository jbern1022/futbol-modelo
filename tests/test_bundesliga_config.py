"""
Bundesliga step 1 (phase 2 expansion): league config, season labels, the
round filter, API-Football name aliases and the Understat club seed.

No database and no network. The 28 API-Football club ids, their spellings
and the 25 Understat names were checked against the live APIs on
2026-10-14; the tests pin the parts the rest of the pipeline relies on.
"""
import pytest

from ingestion import entities
from ingestion.api_football import (
    API_LEAGUE_IDS,
    CROSS_YEAR_LEAGUES,
    NAME_ALIASES,
    regular_season_only,
    resolve_league_id,
    season_label_for,
)
from ingestion.loader import LEAGUES, _season_label

BUNDESLIGA_UNDERSTAT_CLUBS = 25


def _fx(round_name):
    return {"league": {"round": round_name}, "fixture": {"id": 1}}


def test_season_label_is_cross_year_and_matches_the_loader():
    assert "BUNDESLIGA" in CROSS_YEAR_LEAGUES
    assert season_label_for("BUNDESLIGA", 2026) == "2026-27"
    assert season_label_for("BUNDESLIGA", 2025) == _season_label("2526")


def test_league_id_is_explicit_and_needs_no_search():
    # session=None would blow up if the name search were attempted
    assert API_LEAGUE_IDS["BUNDESLIGA"] == 78
    assert resolve_league_id(None, "BUNDESLIGA") == 78


def test_loader_knows_the_league():
    assert LEAGUES["BUNDESLIGA"]["soccerdata"] == "GER-Bundesliga"
    assert LEAGUES["BUNDESLIGA"]["code"] == "BUNDESLIGA"


def test_relegation_playoff_rounds_are_dropped_for_the_bundesliga():
    fixtures = [_fx("Regular Season - 1"), _fx("Regular Season - 34"),
                _fx("Relegation Round"), _fx("Final")]
    kept = regular_season_only("BUNDESLIGA", fixtures)
    assert [f["league"]["round"] for f in kept] == ["Regular Season - 1", "Regular Season - 34"]


def test_other_leagues_are_not_filtered():
    fixtures = [_fx("Regular Season - 1"), _fx("Play-offs")]
    assert regular_season_only("EPL", fixtures) is fixtures
    assert regular_season_only("MLS", fixtures) is fixtures


@pytest.mark.parametrize("variant,canonical", [
    ("Bayern München", "Bayern Munich"),
    ("Borussia Mönchengladbach", "Borussia Monchengladbach"),
    ("Vfl Bochum", "VfL Bochum"),
    ("FC Heidenheim", "1. FC Heidenheim"),
])
def test_api_spelling_variants_collapse_to_one_team_name(variant, canonical):
    assert NAME_ALIASES[variant] == canonical


EXPECTED_UNDERSTAT = {
    "1. FC Heidenheim": "FC Heidenheim", "1. FC Köln": "FC Cologne", "1899 Hoffenheim": "Hoffenheim",
    "Arminia Bielefeld": "Arminia Bielefeld", "Bayer Leverkusen": "Bayer Leverkusen",
    "Bayern Munich": "Bayern Munich", "Borussia Dortmund": "Borussia Dortmund",
    "Borussia Monchengladbach": "Borussia M.Gladbach", "Eintracht Frankfurt": "Eintracht Frankfurt",
    "FC Augsburg": "Augsburg", "FC Schalke 04": "Schalke 04", "FC St. Pauli": "St. Pauli",
    "FSV Mainz 05": "Mainz 05", "Hamburger SV": "Hamburger SV", "Hertha Berlin": "Hertha Berlin",
    "Holstein Kiel": "Holstein Kiel", "RB Leipzig": "RasenBallsport Leipzig", "SC Freiburg": "Freiburg",
    "SV Darmstadt 98": "Darmstadt", "SpVgg Greuther Furth": "Greuther Fuerth",
    "Union Berlin": "Union Berlin", "VfB Stuttgart": "VfB Stuttgart", "VfL Bochum": "Bochum",
    "VfL Wolfsburg": "Wolfsburg", "Werder Bremen": "Werder Bremen",
}


def test_every_understat_name_resolves_to_its_canonical_club():
    assert len(EXPECTED_UNDERSTAT) == BUNDESLIGA_UNDERSTAT_CLUBS
    for canonical, understat_name in EXPECTED_UNDERSTAT.items():
        assert entities.TEAM_SEED[canonical]["understat"] == understat_name
        assert entities.resolve_team("understat", understat_name) == canonical


def test_canonical_names_are_the_names_the_api_route_creates():
    """resolve_or_create_team_id stores NAME_ALIASES.get(api_name, api_name);
    the canonical name must be a fixed point of that mapping, or the Understat
    link would look for a team row that does not exist."""
    for canonical in EXPECTED_UNDERSTAT:
        assert NAME_ALIASES.get(canonical, canonical) == canonical


def test_known_understat_spellings():
    assert entities.resolve_team("understat", "RasenBallsport Leipzig") == "RB Leipzig"
    assert entities.resolve_team("understat", "FC Cologne") == "1. FC Köln"
    assert entities.resolve_team("understat", "Borussia M.Gladbach") == "Borussia Monchengladbach"
    assert entities.resolve_team("understat", "Greuther Fuerth") == "SpVgg Greuther Furth"


def test_unknown_understat_name_still_fails_loudly():
    with pytest.raises(entities.UnknownTeamError):
        entities.resolve_team("understat", "Not A Bundesliga Club")


def test_no_two_clubs_share_a_normalised_understat_name():
    seen = {}
    for canonical, sources in entities.TEAM_SEED.items():
        if "understat" not in sources:
            continue
        key = entities._norm(sources["understat"])
        assert seen.setdefault(key, canonical) == canonical, (key, seen[key], canonical)
