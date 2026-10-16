"""
NFL injury-report gate (Todoist 6hhrVmC7HwQGQvj7): pure helpers only, no network.
Rules under test: only Out and Doubtful are excluded; Questionable, practice-only
(no game status) and other-week rows exclude nobody; failures fall back to the
roster gate with a warning; the per-game merge does not mutate the roster map.
"""
from models.nfl_player_props import (depth_roster_disagreement, injury_exclusions,
                                     safe_injury_report, week_from_game_id)


def _row(gsis, week, status, injury=None):
    return {"gsis_id": gsis, "week": week, "report_status": status, "report_primary_injury": injury}


def test_week_is_read_from_the_game_id():
    assert week_from_game_id("2026_05_TB_CAR") == 5
    assert week_from_game_id("2026_12_KC_DEN") == 12
    assert week_from_game_id(None) is None
    assert week_from_game_id("garbage") is None
    assert week_from_game_id("2026_xx_A_B") is None


def test_only_out_and_doubtful_for_that_week_are_excluded():
    rows = [_row("A", 5, "Out", "Knee"), _row("B", 5, "Doubtful", "Ankle"),
            _row("C", 5, "Questionable", "Hamstring"), _row("D", 5, None),
            _row("E", 5, float("nan")), _row("F", 6, "Out", "Back")]
    got = injury_exclusions(rows, 5)
    assert set(got) == {"A", "B"}
    assert "Out (Knee)" in got["A"] and "week 5" in got["A"]
    assert "Doubtful (Ankle)" in got["B"]


def test_status_matching_ignores_case_and_whitespace():
    assert set(injury_exclusions([_row("A", 3, " OUT "), _row("B", 3, "doubtful")], 3)) == {"A", "B"}


def test_most_restrictive_status_wins_for_duplicate_rows():
    got = injury_exclusions([_row("A", 4, "Doubtful", "Knee"), _row("A", 4, "Out", "Knee")], 4)
    assert got["A"].startswith("listed Out")
    got = injury_exclusions([_row("A", 4, "Out", "Knee"), _row("A", 4, "Doubtful", "Knee")], 4)
    assert got["A"].startswith("listed Out")


def test_unknown_week_or_missing_ids_exclude_nobody():
    assert injury_exclusions([_row("A", 5, "Out")], None) == {}
    assert injury_exclusions([_row(None, 5, "Out"), _row("", 5, "Out")], 5) == {}


def test_injured_depth_chart_players_are_flagged_by_the_existing_helper():
    chart = {("TB", "QB"): ["QB1", "QB2"], ("TB", "RB"): ["RB1"]}
    injured = injury_exclusions([_row("QB1", 5, "Out", "Hamstring")], 5)
    assert depth_roster_disagreement(chart, injured) == [("TB", "QB", "QB1")]


def test_merging_with_the_roster_map_does_not_change_it():
    reserved = {"IR1": "on injured reserve"}
    before = dict(reserved)
    merged = {**injury_exclusions([_row("A", 5, "Out")], 5), **reserved}
    assert reserved == before and set(merged) == {"A", "IR1"}


def test_a_loader_failure_falls_back_with_a_warning():
    def boom(season):
        raise RuntimeError("nflverse is down")
    rows, warning = safe_injury_report(boom, 2026)
    assert rows is None and "roster gate alone" in warning and "nflverse is down" in warning


def test_a_working_loader_returns_rows_and_no_warning():
    rows, warning = safe_injury_report(lambda season: [_row("A", 5, "Out")], 2026)
    assert rows == [_row("A", 5, "Out")] and warning is None
