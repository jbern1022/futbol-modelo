"""
Regression test for the rolling-window drift query in
scripts/check_model_drift.py (DRIFT_SQL) -- closes the "Model drift /
streak monitoring" ticket's detection half (alerting via ntfy is
separate and optional, gated on NTFY_URL/NTFY_TOPIC being set).

Verified against a synthetic league/season/teams/matches/predictions
set inside one transaction that's always rolled back, so it doesn't
depend on (or affect) real graded predictions. Uses round, exact
numbers specifically so the expected stated/realized values are exact,
not statistical.
"""
import os
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from check_model_drift import DRIFT_SQL

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def _seed(cur):
    cur.execute(
        """INSERT INTO futbol.leagues (code, name) VALUES ('TEST_DRIFT_LEAGUE', 'Test Drift League')
           RETURNING league_id""")
    league_id = cur.fetchone()[0]

    cur.execute(
        """INSERT INTO futbol.seasons (league_id, label, start_date, end_date)
           VALUES (%s, '2025-26', '2025-08-01', NULL) RETURNING season_id""",
        (league_id,))
    season_id = cur.fetchone()[0]

    cur.execute("INSERT INTO futbol.teams (name) VALUES ('Test Drift Home') RETURNING team_id")
    home_id = cur.fetchone()[0]
    cur.execute("INSERT INTO futbol.teams (name) VALUES ('Test Drift Away') RETURNING team_id")
    away_id = cur.fetchone()[0]

    cur.execute(
        """INSERT INTO futbol.model_versions (model_name, version_tag)
           VALUES ('test_drift_model', 'v1') RETURNING model_version_id""")
    model_version_id = cur.fetchone()[0]

    now = datetime.now(timezone.utc)

    def make_prediction(days_ago: float, outcome: str) -> None:
        kickoff = now - timedelta(days=days_ago)
        locked_at = kickoff - timedelta(hours=1)
        cur.execute(
            """INSERT INTO futbol.matches (season_id, home_team_id, away_team_id, kickoff_utc, status)
               VALUES (%s, %s, %s, %s, 'final') RETURNING match_id""",
            (season_id, home_id, away_id, kickoff))
        match_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO futbol.predictions
                   (match_id, model_version_id, market, statement, side,
                    probability, created_at, locked_at)
               VALUES (%s, %s, '1X2', 'test — drift check', 'home', 0.6, %s, %s)
               RETURNING prediction_id""",
            (match_id, model_version_id, locked_at, locked_at))
        prediction_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO futbol.prediction_grades
                   (prediction_id, outcome, actual_value, graded_at, grader_version)
               VALUES (%s, %s, NULL, now(), 'test')""",
            (prediction_id, outcome))

    # 20 older matches, exactly 12 hits / 8 misses -- realized_rate =
    # 0.6, perfectly matching stated 0.6, no drift.
    for i in range(20):
        make_prediction(days_ago=100 + i, outcome="hit" if i < 12 else "miss")

    # 10 more recent matches, all misses -- realized_rate = 0.0 against
    # stated 0.6, a real 0.6 drift, and more recent (smaller days_ago)
    # than every one of the 20 above.
    for i in range(10):
        make_prediction(days_ago=i, outcome="miss")

    return league_id


def test_narrow_window_catches_recent_drift_diluted_by_wider_window(conn):
    cur = conn.cursor()
    league_id = _seed(cur)

    # Window covering only the 10 most recent (all misses): full drift visible.
    cur.execute(DRIFT_SQL, (10, 5))
    rows = {(league, market): (n, float(stated), float(realized))
           for league, market, n, stated, realized in cur.fetchall()}
    n, stated, realized = rows[("TEST_DRIFT_LEAGUE", "1X2")]
    assert n == 10
    assert stated == 0.6
    assert realized == 0.0

    # Window covering all 30: diluted by the 20 well-calibrated older ones.
    cur.execute(DRIFT_SQL, (30, 5))
    rows = {(league, market): (n, float(stated), float(realized))
           for league, market, n, stated, realized in cur.fetchall()}
    n, stated, realized = rows[("TEST_DRIFT_LEAGUE", "1X2")]
    assert n == 30
    assert stated == 0.6
    assert realized == 0.4  # (12 hits out of 30)


def test_min_n_excludes_undersized_windows(conn):
    cur = conn.cursor()
    _seed(cur)

    # Only 10 real graded predictions exist for a window of 5 -- but
    # min_n=15 should exclude this (league, market) entirely.
    cur.execute(DRIFT_SQL, (5, 15))
    rows = {(league, market) for league, market, *_ in cur.fetchall()}
    assert ("TEST_DRIFT_LEAGUE", "1X2") not in rows
