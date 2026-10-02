"""
Regression tests for the 3-day slate window (ADR-012).

The real incident (2026-10-02): a manual generate_nfl_slate.py run on
2026-09-06 slated 180 NFL games through December in one batch. The
cron only fills fixtures with no predictions at all, so every later run
wrote 0 rows and the whole season stayed frozen on 2026-09-06's depth
chart -- De'Von Achane (torn ACL, Week 3, placed on IR) kept getting
rushing-yards predictions for every remaining Dolphins game.

The DB-backed test runs inside one transaction that is always rolled
back -- nothing it does is ever visible outside it.
"""
import datetime
import os

import psycopg2
import pytest

from predictions.slate_window import (
    SLATE_WINDOW_DAYS,
    clamp_days_ahead,
    has_live_slate,
    nfl_reserve_reason,
    soccer_absence_reason,
    stale_void_reason,
)


def test_window_is_three_days():
    assert SLATE_WINDOW_DAYS == 3


def test_clamp_caps_a_wide_manual_run_at_the_window():
    # The 2026-09-06 run that froze the NFL season would have been capped here.
    assert clamp_days_ahead(14) == 3
    assert clamp_days_ahead(120) == 3


def test_clamp_keeps_a_narrower_window():
    assert clamp_days_ahead(1) == 1


def test_clamp_rejects_nonpositive():
    with pytest.raises(ValueError):
        clamp_days_ahead(0)


def test_nfl_reserve_injured_reads_as_ir():
    # Achane's real nflverse weekly-roster row from Week 4 on: RES / R01.
    assert nfl_reserve_reason("RES", "R01") == "on Reserve/Injured (IR)"
    assert nfl_reserve_reason("RES", "R48") == "on Reserve/Injured (IR)"


def test_nfl_unknown_reserve_code_is_not_guessed():
    assert nfl_reserve_reason("RES", "R27") == "on a reserve list (nflverse code R27)"


def test_nfl_active_player_has_no_reason():
    assert nfl_reserve_reason("ACT", "A01") is None


def test_soccer_cards_read_as_suspension():
    assert soccer_absence_reason("Red Card") == "suspended (Red Card)"
    assert soccer_absence_reason("Yellow Cards") == "suspended (Yellow Cards)"


def test_soccer_other_reasons_read_as_injury_or_absence():
    assert soccer_absence_reason("Knee Injury") == "out (Knee Injury)"


def test_void_reason_names_the_absence_first():
    reason = stale_void_reason(28, absence="on Reserve/Injured (IR)")
    assert reason.startswith("Player on Reserve/Injured (IR).")
    assert "28 days before kickoff" in reason
    assert "ADR-012" in reason


def test_void_reason_without_absence_explains_the_window():
    reason = stale_void_reason(28)
    assert reason.startswith("Slated 28 days before kickoff")
    assert "3-day" in reason


DSN = os.environ.get("FUTBOL_DSN")


@pytest.fixture
def conn():
    if not DSN:
        pytest.skip("FUTBOL_DSN not set -- no live DB to check against")
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def test_a_fully_voided_slate_does_not_count_as_slated(conn):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT m.match_id FROM futbol.matches m
               WHERE m.status = 'scheduled' AND m.kickoff_utc > now() + interval '1 day'
                 AND NOT EXISTS (SELECT 1 FROM futbol.predictions p WHERE p.match_id = m.match_id)
               LIMIT 1""")
        row = cur.fetchone()
        if row is None:
            pytest.skip("no scheduled, unslated match to test against")
        match_id = row[0]
        cur.execute("SELECT model_version_id FROM futbol.model_versions LIMIT 1")
        mvid = cur.fetchone()[0]

        assert has_live_slate(cur, match_id) is False

        now = datetime.datetime.now(datetime.timezone.utc)
        cur.execute(
            """INSERT INTO futbol.predictions
                   (match_id, model_version_id, market, statement, side,
                    probability, created_at, locked_at)
               VALUES (%s, %s, 'MONEYLINE', 'test -- slate window', 'home', 0.6, %s, %s)
               RETURNING prediction_id""", (match_id, mvid, now, now))
        prediction_id = cur.fetchone()[0]
        assert has_live_slate(cur, match_id) is True

        cur.execute(
            """INSERT INTO futbol.prediction_grades
                   (prediction_id, outcome, grader_version, void_reason)
               VALUES (%s, 'void', 'test', 'test')""", (prediction_id,))
        assert has_live_slate(cur, match_id) is False
