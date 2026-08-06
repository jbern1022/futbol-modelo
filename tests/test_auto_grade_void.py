"""
The voiding rules, against a real database.

Voiding is the only operation that removes a prediction from the published
rates, and grading is once-only, so these rules need to be pinned: voiding too
eagerly discards a result that would have arrived, voiding too little leaves
the record computed over a self-selected subset.
"""
from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

_spec = importlib.util.spec_from_file_location(
    "auto_grade", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "auto_grade.py")
auto_grade = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auto_grade)


def make_final_match(db, fx, days_ago: int, hg: int = 2, ag: int = 1) -> int:
    kickoff = datetime.now(timezone.utc) - timedelta(days=days_ago)
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO futbol.matches
                 (season_id, home_team_id, away_team_id, kickoff_utc, status,
                  home_goals, away_goals)
               VALUES (%s,%s,%s,%s,'final',%s,%s) RETURNING match_id""",
            (fx["season_id"], fx["home_team_id"], fx["away_team_id"],
             kickoff, hg, ag))
        return cur.fetchone()[0]


def add_prediction(db, fx, match_id: int, market: str, side: str, line=None,
                   team_id="home", player_id=None) -> int:
    subject_team = fx["home_team_id"] if team_id == "home" else team_id
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO futbol.predictions
                 (match_id, model_version_id, market, subject_team_id,
                  subject_player_id, statement, line, side, probability, locked_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       (SELECT kickoff_utc - interval '2 hours'
                        FROM futbol.matches WHERE match_id = %s))
               RETURNING prediction_id""",
            (match_id, fx["model_version_id"], market,
             None if player_id else subject_team, player_id,
             f"{market} test", line, side, 0.6, match_id))
        return cur.fetchone()[0]


def grade_of(db, prediction_id: int):
    with db.cursor() as cur:
        cur.execute(
            "SELECT outcome, void_reason FROM futbol.prediction_grades "
            "WHERE prediction_id = %s", (prediction_id,))
        return cur.fetchone()


# ---------- normal grading still works ----------

def test_gradeable_prediction_is_graded_not_voided(db, fixture_row):
    match_id = make_final_match(db, fixture_row, days_ago=1)
    pid = add_prediction(db, fixture_row, match_id, "1X2", "home")
    auto_grade.run(db, verbose=False)
    assert grade_of(db, pid) == ("hit", None)


def test_count_market_with_stats_is_graded(db, fixture_row):
    match_id = make_final_match(db, fixture_row, days_ago=1)
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO futbol.team_match_stats (match_id, team_id, is_home, corners)
               VALUES (%s,%s,TRUE,7)""", (match_id, fixture_row["home_team_id"]))
    pid = add_prediction(db, fixture_row, match_id, "CORNERS", "over", 4.5)
    auto_grade.run(db, verbose=False)
    assert grade_of(db, pid) == ("hit", None)


# ---------- player absent: decidable immediately ----------

def test_absent_player_is_voided_immediately(db, fixture_row):
    """Other players have rows, so the match was ingested and this one did not
    feature. Waiting cannot change that, so it must not wait."""
    match_id = make_final_match(db, fixture_row, days_ago=1)
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO futbol.players (full_name) VALUES ('Someone Else')
               RETURNING player_id""")
        other = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO futbol.player_match_stats
                 (match_id, player_id, team_id, minutes, goals)
               VALUES (%s,%s,%s,90,1)""",
            (match_id, other, fixture_row["home_team_id"]))
    pid = add_prediction(db, fixture_row, match_id, "PLAYER_GOALS", "over", 0.5,
                         player_id=fixture_row["player_id"])
    auto_grade.run(db, verbose=False)
    assert grade_of(db, pid) == ("void", auto_grade.VOID_PLAYER_ABSENT)


def test_match_with_no_player_rows_is_not_called_absent(db, fixture_row):
    """No player rows at all means the match was never ingested for players.
    Absence says nothing about whether they played, so this must wait."""
    match_id = make_final_match(db, fixture_row, days_ago=1)
    pid = add_prediction(db, fixture_row, match_id, "PLAYER_GOALS", "over", 0.5,
                         player_id=fixture_row["player_id"])
    auto_grade.run(db, verbose=False)
    assert grade_of(db, pid) is None


# ---------- missing stat: waits out the grace period ----------

def test_recent_missing_stat_is_left_pending(db, fixture_row):
    match_id = make_final_match(db, fixture_row, days_ago=2)
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO futbol.team_match_stats (match_id, team_id, is_home, corners)
               VALUES (%s,%s,TRUE,NULL)""", (match_id, fixture_row["home_team_id"]))
    pid = add_prediction(db, fixture_row, match_id, "CORNERS", "over", 4.5)
    counts = auto_grade.run(db, verbose=False)
    assert grade_of(db, pid) is None
    assert counts["pending"] == 1


def test_old_missing_stat_is_voided(db, fixture_row):
    match_id = make_final_match(db, fixture_row, days_ago=20)
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO futbol.team_match_stats (match_id, team_id, is_home, corners)
               VALUES (%s,%s,TRUE,NULL)""", (match_id, fixture_row["home_team_id"]))
    pid = add_prediction(db, fixture_row, match_id, "CORNERS", "over", 4.5)
    auto_grade.run(db, verbose=False)
    assert grade_of(db, pid) == ("void", auto_grade.VOID_STAT_UNAVAILABLE)


@pytest.mark.parametrize("days_ago,expect_void", [(13, False), (14, True), (15, True)])
def test_grace_period_boundary(db, fixture_row, days_ago, expect_void):
    match_id = make_final_match(db, fixture_row, days_ago=days_ago)
    pid = add_prediction(db, fixture_row, match_id, "SOT", "over", 3.5)
    auto_grade.run(db, verbose=False)
    graded = grade_of(db, pid)
    assert (graded is not None) == expect_void
    if expect_void:
        assert graded == ("void", auto_grade.VOID_STAT_UNAVAILABLE)


def test_grace_period_is_configurable(db, fixture_row):
    match_id = make_final_match(db, fixture_row, days_ago=5)
    pid = add_prediction(db, fixture_row, match_id, "SOT", "over", 3.5)
    auto_grade.run(db, verbose=False, grace_days=30)
    assert grade_of(db, pid) is None
    auto_grade.run(db, verbose=False, grace_days=3)
    assert grade_of(db, pid) == ("void", auto_grade.VOID_STAT_UNAVAILABLE)


# ---------- dry run ----------

def test_dry_run_writes_nothing(db, fixture_row):
    match_id = make_final_match(db, fixture_row, days_ago=20)
    pid = add_prediction(db, fixture_row, match_id, "CORNERS", "over", 4.5)
    counts = auto_grade.run(db, dry_run=True, verbose=False)
    assert counts["voided"] == 1
    assert grade_of(db, pid) is None, "dry run must not write to the ledger"


# ---------- the reason column is constrained ----------

def test_a_reason_cannot_be_attached_to_a_hit(db, fixture_row):
    """void_reason carries void semantics; allowing it on a hit would let a
    graded prediction claim to have been voided."""
    match_id = make_final_match(db, fixture_row, days_ago=1)
    pid = add_prediction(db, fixture_row, match_id, "1X2", "home")
    with pytest.raises(Exception):
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO futbol.prediction_grades
                     (prediction_id, outcome, grader_version, void_reason)
                   VALUES (%s,'hit','t',%s)""",
                (pid, auto_grade.VOID_STAT_UNAVAILABLE))


# ---------- voids are excluded from the rates but stay visible ----------

def test_voids_are_excluded_from_the_scorecard_but_counted_in_the_summary(db, fixture_row):
    """
    The whole point of publishing voids: they must not drag a hit rate down,
    and they must not vanish without trace either.
    """
    hit_match = make_final_match(db, fixture_row, days_ago=1)
    add_prediction(db, fixture_row, hit_match, "1X2", "home")

    void_match = make_final_match(db, fixture_row, days_ago=20)
    add_prediction(db, fixture_row, void_match, "CORNERS", "over", 4.5)

    auto_grade.run(db, verbose=False)

    with db.cursor() as cur:
        cur.execute("SELECT market, n_predictions FROM futbol.v_season_scorecard")
        scorecard = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT void_reason, n FROM futbol.v_void_summary")
        voids = {r[0]: r[1] for r in cur.fetchall()}

    assert scorecard.get("1X2") == 1, "the graded prediction should be in the rates"
    assert "CORNERS" not in scorecard, "a void must not appear as a graded result"
    assert voids.get(auto_grade.VOID_STAT_UNAVAILABLE) == 1, "the void must still be visible"
