"""
Regression test for the aggregation query in scripts/daily_digest.py
(GRADED_LAST_24H_SQL) -- closes the "Daily digest via ntfy" ticket's
detection half.

Verified against synthetic league/season/teams/matches/predictions
inside one transaction that's always rolled back, isolated from real
graded predictions via a fabricated league code.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from daily_digest import GRADED_LAST_24H_SQL

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def test_counts_recent_grades_by_league_and_outcome(conn):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO futbol.leagues (code, name) VALUES ('TEST_DIGEST_LEAGUE', 'Test Digest League')
           RETURNING league_id""")
    league_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO futbol.seasons (league_id, label, start_date, end_date)
           VALUES (%s, '2025-26', '2025-08-01', NULL) RETURNING season_id""",
        (league_id,))
    season_id = cur.fetchone()[0]
    cur.execute("INSERT INTO futbol.teams (name) VALUES ('Test Digest Home') RETURNING team_id")
    home_id = cur.fetchone()[0]
    cur.execute("INSERT INTO futbol.teams (name) VALUES ('Test Digest Away') RETURNING team_id")
    away_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO futbol.model_versions (model_name, version_tag)
           VALUES ('test_digest_model', 'v1') RETURNING model_version_id""")
    model_version_id = cur.fetchone()[0]

    now = datetime.now(timezone.utc)

    def make_graded(outcome: str, graded_hours_ago: float) -> None:
        # kickoff varies per call (offset by graded_hours_ago, already
        # distinct across every call site below) -- matches has a real
        # UNIQUE constraint on (season_id, home_team_id, away_team_id,
        # kickoff_utc), so identical kickoffs across calls would collide.
        kickoff = now - timedelta(days=1, seconds=graded_hours_ago)
        cur.execute(
            """INSERT INTO futbol.matches (season_id, home_team_id, away_team_id, kickoff_utc, status)
               VALUES (%s, %s, %s, %s, 'final') RETURNING match_id""",
            (season_id, home_id, away_id, kickoff))
        match_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO futbol.predictions
                   (match_id, model_version_id, market, statement, side,
                    probability, created_at, locked_at)
               VALUES (%s, %s, '1X2', 'test — digest', 'home', 0.6, %s, %s)
               RETURNING prediction_id""",
            (match_id, model_version_id, kickoff - timedelta(hours=1), kickoff - timedelta(hours=1)))
        prediction_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO futbol.prediction_grades
                   (prediction_id, outcome, actual_value, graded_at, grader_version)
               VALUES (%s, %s, NULL, %s, 'test')""",
            (prediction_id, outcome, now - timedelta(hours=graded_hours_ago)))

    # Within the last 24h: 2 hits, 1 miss.
    make_graded("hit", graded_hours_ago=2)
    make_graded("hit", graded_hours_ago=5)
    make_graded("miss", graded_hours_ago=10)
    # Outside the window -- must not be counted.
    make_graded("hit", graded_hours_ago=30)

    cur.execute(GRADED_LAST_24H_SQL)
    rows = {(league, outcome): n for league, outcome, n in cur.fetchall()
           if league == "TEST_DIGEST_LEAGUE"}

    assert rows[("TEST_DIGEST_LEAGUE", "hit")] == 2
    assert rows[("TEST_DIGEST_LEAGUE", "miss")] == 1
    assert ("TEST_DIGEST_LEAGUE", "void") not in rows
