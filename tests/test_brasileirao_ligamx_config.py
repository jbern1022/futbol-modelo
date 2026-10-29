"""
Brasileirao and Liga MX, step 1 of docs/ADDING_A_LEAGUE.md (route B, ADR-019): config only.
Checked against the live API on 2026-10-29:
  Brasileirao (id 71): calendar-year seasons (2026 runs 2026-01-28 to 2026-12-02), 380 regular-season
    fixtures, 20 clubs, no play-off rounds, no club spelled two ways, no overlap with futbol.teams.
  Liga MX (id 262): ONE API season holds two tournaments (2025 = Apertura 2025 + Clausura 2026), 153
    regular fixtures each, then Play-In / Quarter-finals / Semi-finals / Final named 'Apertura - ...' and
    'Clausura - ...'. Owner decision 2026-10-25: shared cross-year API season, separate Apertura and
    Clausura partitions, regular season first, Liguilla deferred.
"""
import pytest

from ingestion.api_football import (
    API_LEAGUE_IDS,
    CROSS_YEAR_LEAGUES,
    LEAGUE_SEARCH,
    liga_mx_tournament,
    regular_season_only,
    resolve_league_id,
    season_label_for,
)


def _fx(round_name):
    return {"league": {"round": round_name}, "fixture": {"id": 1}}


def test_ids_are_explicit_because_a_name_search_would_find_italys_serie_a():
    assert LEAGUE_SEARCH["BRASILEIRAO"] == ("Serie A", "Brazil")
    assert API_LEAGUE_IDS["BRASILEIRAO"] == 71 and resolve_league_id(None, "BRASILEIRAO") == 71
    assert LEAGUE_SEARCH["LIGA_MX"] == ("Liga MX", "Mexico")
    assert API_LEAGUE_IDS["LIGA_MX"] == 262 and resolve_league_id(None, "LIGA_MX") == 262


def test_brasileirao_uses_a_bare_calendar_year_label_and_liga_mx_a_cross_year_one():
    assert "BRASILEIRAO" not in CROSS_YEAR_LEAGUES
    assert season_label_for("BRASILEIRAO", 2026) == "2026"
    assert "LIGA_MX" in CROSS_YEAR_LEAGUES
    assert season_label_for("LIGA_MX", 2026) == "2026-27"
    assert season_label_for("LIGA_MX", 2025) == "2025-26"


def test_brasileirao_feed_is_all_regular_season_so_nothing_is_filtered():
    fixtures = [_fx("Regular Season - 1"), _fx("Regular Season - 38")]
    assert regular_season_only("BRASILEIRAO", fixtures) is fixtures


def test_liga_mx_keeps_only_numbered_apertura_and_clausura_rounds():
    fixtures = [_fx("Apertura - 1"), _fx("Apertura - 17"), _fx("Clausura - 1"), _fx("Clausura - 17"),
                _fx("Apertura - Play-In Semi-finals"), _fx("Apertura - Play-In Final"),
                _fx("Apertura - Quarter-finals"), _fx("Apertura - Semi-finals"), _fx("Apertura - Final"),
                _fx("Clausura - Quarter-finals"), _fx("Clausura - Final")]
    kept = [f["league"]["round"] for f in regular_season_only("LIGA_MX", fixtures)]
    assert kept == ["Apertura - 1", "Apertura - 17", "Clausura - 1", "Clausura - 17"]


def test_liga_mx_filter_tolerates_missing_rounds():
    assert regular_season_only("LIGA_MX", [{"league": {"round": None}, "fixture": {"id": 1}}]) == []


@pytest.mark.parametrize("round_name,tournament", [
    ("Apertura - 3", "Apertura"), ("Clausura - 17", "Clausura"),
    ("Apertura - Quarter-finals", "Apertura"), ("Clausura - Final", "Clausura"),
])
def test_tournament_is_named_from_the_round(round_name, tournament):
    assert liga_mx_tournament(round_name) == tournament


@pytest.mark.parametrize("bad", [None, "", "Regular Season - 3", "Liguilla"])
def test_tournament_is_none_for_anything_else(bad):
    assert liga_mx_tournament(bad) is None


def test_earlier_leagues_are_unaffected():
    fixtures = [_fx("Regular Season - 1"), _fx("Final")]
    assert regular_season_only("EPL", fixtures) is fixtures
    assert [f["league"]["round"] for f in regular_season_only("BUNDESLIGA", fixtures)] == ["Regular Season - 1"]
