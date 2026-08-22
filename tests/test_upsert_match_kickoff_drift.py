"""
Regression test for the duplicate-match bug (see Todoist): a kickoff-
time correction between ingestion runs used to insert a second match
row instead of updating the existing one, because the old ON CONFLICT
target (season_id, home_team_id, away_team_id, kickoff_utc) treats
kickoff_utc as part of the fixture's identity. Found live: 9 real
fixtures duplicated this way, 139 predictions permanently stuck on
the orphaned side (voided; see sql/void_duplicate_match_predictions.sql).

upsert_match() now looks up by external_ref first. Runs against the
live DB in an explicit transaction that's always rolled back --
skips cleanly without FUTBOL_DSN.
"""
import datetime
import os

import psycopg2
import pytest

from ingestion.loader import upsert_match

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def test_kickoff_correction_updates_existing_row_instead_of_duplicating(conn):
    cur = conn.cursor()
    cur.execute("SELECT home_team_id, away_team_id, season_id FROM futbol.matches LIMIT 1")
    hid, aid, sid = cur.fetchone()
    ext_ref = "test:kickoff-drift-regression"
    original_kickoff = datetime.datetime(2099, 6, 1, 12, 0, tzinfo=datetime.timezone.utc)
    corrected_kickoff = original_kickoff.replace(hour=15)

    first_id = upsert_match(cur, sid, hid, aid, original_kickoff, None, None, "scheduled", ext_ref)
    second_id = upsert_match(cur, sid, hid, aid, corrected_kickoff, 2, 1, "final", ext_ref)

    assert first_id == second_id, "kickoff correction created a new match_id instead of updating"

    cur.execute("SELECT count(*) FROM futbol.matches WHERE external_ref = %s", (ext_ref,))
    assert cur.fetchone()[0] == 1

    cur.execute("SELECT kickoff_utc, status, home_score FROM futbol.matches WHERE match_id = %s", (first_id,))
    kickoff, status, home_score = cur.fetchone()
    assert kickoff == corrected_kickoff
    assert status == "final"
    assert home_score == 2
