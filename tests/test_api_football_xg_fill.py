"""
API-Football expected_goals fills team_match_stats.xg for the current
season (Understat xG stopped at 2025-26; the CORNERS/SOT models read
xg_for_r5). Rescaled to Understat's scale (scripts/experiment_api_football_xg.py:
corr 0.90-0.92, API-Football ~10% lower), only where xg is NULL, and only
for leagues whose training data has Understat xG. Runs in a rolled-back
transaction.
"""
import os

import psycopg2
import pytest

from ingestion.api_football import API_FOOTBALL_XG_SCALE, store_api_football_xg

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def cur():
    c = psycopg2.connect(DSN)
    yield c.cursor()
    c.rollback()
    c.close()


def _row(cur, has_xg: bool):
    cur.execute(
        f"""SELECT t.match_id, t.team_id, t.xg FROM futbol.team_match_stats t
            JOIN futbol.matches m USING (match_id) JOIN futbol.seasons s USING (season_id)
            JOIN futbol.leagues l USING (league_id)
            WHERE l.code = 'EPL' AND t.xg IS {'NOT ' if has_xg else ''}NULL LIMIT 1""")
    row = cur.fetchone()
    if row is None:
        pytest.skip("no suitable team_match_stats row")
    return row


def _xg(cur, match_id, team_id):
    cur.execute("SELECT xg FROM futbol.team_match_stats WHERE match_id = %s AND team_id = %s",
                (match_id, team_id))
    return cur.fetchone()[0]


def test_fills_a_missing_xg_on_the_understat_scale(cur):
    match_id, team_id, _ = _row(cur, has_xg=False)
    store_api_football_xg(cur, "EPL", match_id, team_id, "1.50")
    assert float(_xg(cur, match_id, team_id)) == pytest.approx(1.50 * API_FOOTBALL_XG_SCALE, abs=1e-3)


def test_never_overwrites_understat_xg(cur):
    match_id, team_id, before = _row(cur, has_xg=True)
    store_api_football_xg(cur, "EPL", match_id, team_id, "0.10")
    assert _xg(cur, match_id, team_id) == before


def test_mls_is_left_alone(cur):
    match_id, team_id, _ = _row(cur, has_xg=False)
    store_api_football_xg(cur, "MLS", match_id, team_id, "1.50")
    assert _xg(cur, match_id, team_id) is None


def test_missing_value_is_a_no_op(cur):
    match_id, team_id, _ = _row(cur, has_xg=False)
    store_api_football_xg(cur, "EPL", match_id, team_id, None)
    assert _xg(cur, match_id, team_id) is None
