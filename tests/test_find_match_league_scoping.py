"""
Regression test for league-scoping in find_match_id() / _find_match():
the same two teams can meet twice in a short window across different
competitions (league + cup, or two different leagues in this synthetic
case), and without a league filter the date+teams lookup could silently
attach stats to the wrong fixture. Runs against the live DB in an
explicit transaction that's always rolled back -- skips cleanly without
FUTBOL_DSN.
"""
import os

import psycopg2
import pytest

from ingestion.api_football import find_match_id
from ingestion.loader import _find_match

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def _make_collision(cur):
    """Same two teams, same calendar day, two different leagues."""
    cur.execute("SELECT home_team_id, away_team_id FROM futbol.matches LIMIT 1")
    hid, aid = cur.fetchone()

    cur.execute(
        """SELECT m.season_id, l.code FROM futbol.matches m
           JOIN futbol.seasons s ON s.season_id = m.season_id
           JOIN futbol.leagues l ON l.league_id = s.league_id
           WHERE m.home_team_id = %s AND m.away_team_id = %s LIMIT 1""",
        (hid, aid))
    sid_a, code_a = cur.fetchone()

    cur.execute(
        """SELECT s.season_id, l.code FROM futbol.seasons s
           JOIN futbol.leagues l ON l.league_id = s.league_id
           WHERE l.code <> %s LIMIT 1""",
        (code_a,))
    sid_b, code_b = cur.fetchone()

    cur.execute(
        """INSERT INTO futbol.matches (season_id, home_team_id, away_team_id, kickoff_utc, status)
           VALUES (%s, %s, %s, '2099-03-01 15:00:00+00', 'final') RETURNING match_id""",
        (sid_a, hid, aid))
    mid_a = cur.fetchone()[0]

    cur.execute(
        """INSERT INTO futbol.matches (season_id, home_team_id, away_team_id, kickoff_utc, status)
           VALUES (%s, %s, %s, '2099-03-01 18:00:00+00', 'final') RETURNING match_id""",
        (sid_b, hid, aid))
    mid_b = cur.fetchone()[0]

    return hid, aid, code_a, mid_a, code_b, mid_b


def test_find_match_id_scoped_by_league(conn):
    cur = conn.cursor()
    hid, aid, code_a, mid_a, code_b, mid_b = _make_collision(cur)

    assert find_match_id(cur, hid, aid, "2099-03-01", code_a) == mid_a
    assert find_match_id(cur, hid, aid, "2099-03-01", code_b) == mid_b
    # Unscoped call (league_code=None) must still work for backward compat --
    # it just can't promise which of the two it picks.
    assert find_match_id(cur, hid, aid, "2099-03-01") in (mid_a, mid_b)


def test_find_match_scoped_by_league(conn):
    cur = conn.cursor()
    hid, aid, code_a, mid_a, code_b, mid_b = _make_collision(cur)

    row_a = {"date": "2099-03-01"}
    assert _find_match(cur, row_a, hid, code_a) == mid_a
    assert _find_match(cur, row_a, hid, code_b) == mid_b
