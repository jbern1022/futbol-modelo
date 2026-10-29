"""Planner for scripts/reconcile_wc_2026.py (Todoist 6hm4XP4q8xPMg9Jf): pure, no DB/API."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from reconcile_wc_2026 import norm_team, plan_reconciliation  # noqa: E402

TEAMS = {"france": 37, "spain": 31, "england": 41, "argentina": 33, "norway": 50, "curacao": 60,
         "germany": 70, "paraguay": 71, "dr congo": 72}


def fx(fid, date, rnd, home, away, status, goals, ft, pen=(None, None)):
    return {"fixture": {"id": fid, "date": f"{date}T19:00:00+00:00", "status": {"short": status}},
            "league": {"round": rnd}, "teams": {"home": {"name": home}, "away": {"name": away}},
            "goals": {"home": goals[0], "away": goals[1]},
            "score": {"fulltime": {"home": ft[0], "away": ft[1]}, "penalty": {"home": pen[0], "away": pen[1]}}}


def row(mid, date, status, home, away, hs=None, as_=None, ot=False, pens=False, stage="Round of 16"):
    return {"match_id": mid, "date": date, "status": status, "stage": stage, "home": home, "away": away,
            "home_id": TEAMS[norm_team(home)], "away_id": TEAMS[norm_team(away)],
            "home_score": hs, "away_score": as_, "went_to_ot": ot, "went_to_pens": pens, "api_id": None}


def plan(api, db):
    return plan_reconciliation(api, db, TEAMS, season_id=1)


def test_norm_team_aliases():
    assert norm_team("Curaçao") == "curacao"
    assert norm_team("Congo DR") == norm_team("DR Congo") == "dr congo"


def test_stale_scheduled_row_becomes_final_with_90min_score_and_pens():
    api = [fx(900, "2026-06-29", "Round of 32", "Germany", "Paraguay", "PEN", (1, 1), (1, 1), (3, 4))]
    db = [row(75, "2026-06-29", "scheduled", "Germany", "Paraguay")]
    p = plan(api, db)
    (u,) = p["updates"]
    assert u["match_id"] == 75 and u["set"] == {
        "status": "final", "home_score": 1, "away_score": 1, "went_to_ot": True, "went_to_pens": True,
        "pens_home": 3, "pens_away": 4, "api_football_fixture_id": 900}
    assert p["inserts"] == [] and p["unresolved"] == []


def test_orientation_is_followed_when_db_home_is_api_away():
    api = [fx(901, "2026-07-09", "Quarter-finals", "Spain", "France", "FT", (1, 2), (1, 2))]
    db = [row(97, "2026-07-09", "scheduled", "France", "Spain")]
    (u,) = plan(api, db)["updates"]
    assert (u["set"]["home_score"], u["set"]["away_score"]) == (2, 1)


def test_missing_matches_are_inserted_with_stage_and_api_ref():
    api = [fx(910, "2026-07-14", "Semi-finals", "France", "Spain", "FT", (0, 2), (0, 2)),
           fx(911, "2026-07-18", "3rd Place Final", "France", "England", "FT", (4, 6), (4, 6)),
           fx(912, "2026-07-19", "Final", "Spain", "Argentina", "AET", (1, 0), (0, 0))]
    ins = plan(api, [])["inserts"]
    assert [i["stage"] for i in ins] == ["Semi-finals", "Third place", "Final"]
    f = ins[2]
    assert f["external_ref"] == "api-football:912" and f["status"] == "final"
    assert (f["home_score"], f["away_score"], f["went_to_ot"], f["went_to_pens"]) == (0, 0, True, False)
    assert f["season_id"] == 1 and f["home_team_id"] == 31 and f["away_team_id"] == 33


def test_unresolvable_team_is_reported_not_created():
    api = [fx(920, "2026-07-14", "Semi-finals", "Atlantis", "Spain", "FT", (0, 1), (0, 1))]
    p = plan(api, [])
    assert p["inserts"] == [] and "Atlantis" in p["unresolved"][0]


def test_final_row_with_post_et_score_is_a_score_fix_not_a_default_update():
    api = [fx(930, "2026-07-01", "Round of 32", "Argentina", "Norway", "AET", (3, 2), (1, 1))]
    db = [row(86, "2026-07-01", "final", "Argentina", "Norway", 3, 2)]
    p = plan(api, db)
    assert p["updates"] == []
    (s,) = p["score_fixes"]
    assert s["match_id"] == 86 and s["set"] == {"home_score": 1, "away_score": 1}
    (f,) = p["flag_fixes"]
    assert f["match_id"] == 86 and f["set"]["went_to_ot"] is True


def test_correct_90min_final_row_only_gets_flag_fix_and_never_a_score_change():
    # the match-100 case: DB 1-1 is already the 90-minute score; API goals (1-2) include extra time
    api = [fx(940, "2026-07-11", "Quarter-finals", "Norway", "England", "AET", (1, 2), (1, 1))]
    db = [row(100, "2026-07-11", "final", "Norway", "England", 1, 1)]
    p = plan(api, db)
    assert p["score_fixes"] == []
    assert [f["match_id"] for f in p["flag_fixes"]] == [100]


def test_repeat_pairing_picks_the_nearest_date_and_uses_each_row_once():
    api = [fx(950, "2026-06-20", "Group Stage - 2", "England", "Norway", "FT", (2, 0), (2, 0)),
           fx(951, "2026-07-11", "Quarter-finals", "England", "Norway", "FT", (1, 0), (1, 0))]
    db = [row(1, "2026-06-20", "final", "England", "Norway", 2, 0, stage="Group stage"),
          row(2, "2026-07-11", "scheduled", "England", "Norway")]
    p = plan(api, db)
    assert [u["match_id"] for u in p["updates"]] == [2] and p["inserts"] == []


def test_matched_rows_get_their_fixture_id_filled():
    api = [fx(960, "2026-06-20", "Group Stage - 2", "England", "Norway", "FT", (2, 0), (2, 0))]
    db = [row(1, "2026-06-20", "final", "England", "Norway", 2, 0, stage="Group stage")]
    (a,) = plan(api, db)["fixture_ids"]
    assert a["match_id"] == 1 and a["set"] == {"api_football_fixture_id": 960}


def test_unfinished_api_fixture_is_ignored():
    api = [fx(970, "2026-07-14", "Semi-finals", "France", "Spain", "NS", (None, None), (None, None))]
    p = plan(api, [])
    assert p["inserts"] == [] and p["updates"] == []
