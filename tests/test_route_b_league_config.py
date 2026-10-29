"""
Ligue 1 and Eredivisie, step 1 of docs/ADDING_A_LEAGUE.md (route B: API-Football only, ADR-019):
league config, season labels, explicit ids and the regular-season filter. Config only: no database,
no network, no CronJobs, no switch in section 3 turned on.

Checked against the live API on 2026-10-29: both feeds' 2026 season is 306 regular-season fixtures and
18 clubs; the 2025 feeds also list play-off rounds ('Final', 'Semi-finals'); no club is spelled two ways
for one id; no club name is already in futbol.teams.
"""
import pytest

from ingestion.api_football import (
    API_LEAGUE_IDS,
    CROSS_YEAR_LEAGUES,
    LEAGUE_SEARCH,
    NAME_ALIASES,
    regular_season_only,
    resolve_league_id,
    season_label_for,
)

LEAGUES = [("LIGUE_1", 61, "Ligue 1", "France"), ("EREDIVISIE", 88, "Eredivisie", "Netherlands")]


def _fx(round_name):
    return {"league": {"round": round_name}, "fixture": {"id": 1}}


@pytest.mark.parametrize("code,api_id,name,country", LEAGUES)
def test_league_is_searchable_and_has_an_explicit_id(code, api_id, name, country):
    assert LEAGUE_SEARCH[code] == (name, country)
    assert API_LEAGUE_IDS[code] == api_id
    assert resolve_league_id(None, code) == api_id  # session=None: a name search would blow up


@pytest.mark.parametrize("code", [c[0] for c in LEAGUES])
def test_season_label_is_cross_year(code):
    assert code in CROSS_YEAR_LEAGUES
    assert season_label_for(code, 2026) == "2026-27"
    assert season_label_for(code, 2025) == "2025-26"


@pytest.mark.parametrize("code", [c[0] for c in LEAGUES])
def test_playoff_rounds_are_dropped(code):
    fixtures = [_fx("Regular Season - 1"), _fx("Regular Season - 34"), _fx("Semi-finals"), _fx("Final")]
    kept = regular_season_only(code, fixtures)
    assert [f["league"]["round"] for f in kept] == ["Regular Season - 1", "Regular Season - 34"]


def test_existing_leagues_are_untouched():
    fixtures = [_fx("Regular Season - 1"), _fx("Final")]
    for code in ("EPL", "SERIE_A", "LA_LIGA", "MLS"):
        assert regular_season_only(code, fixtures) is fixtures
    assert API_LEAGUE_IDS["BUNDESLIGA"] == 78 and "BUNDESLIGA" in CROSS_YEAR_LEAGUES


def test_no_aliases_are_needed_because_no_club_has_two_spellings():
    assert not any(k for k in NAME_ALIASES if k in ("Paris Saint Germain", "PSV Eindhoven", "Ajax"))
