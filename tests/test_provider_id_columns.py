"""
Migration 0041: per-provider match ids. external_ref holds only one
provider's id, so Understat-created EPL/SERIE_A/LA_LIGA rows could never
carry an API-Football fixture id, and loading one provider's data onto
the other's rows dropped shots or created duplicate matches. Rolled back.
"""
import os

import psycopg2
import pytest

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def cur():
    c = psycopg2.connect(DSN)
    yield c.cursor()
    c.rollback()
    c.close()


def test_trigger_fills_the_api_football_id_from_external_ref(cur):
    cur.execute("""SELECT match_id FROM futbol.matches
                   WHERE external_ref IS NULL AND api_football_fixture_id IS NULL LIMIT 1""")
    row = cur.fetchone()
    if row is None:
        pytest.skip("no match row without a ref")
    cur.execute("UPDATE futbol.matches SET external_ref = 'api-football:999999999' WHERE match_id = %s "
                "RETURNING api_football_fixture_id", (row[0],))
    assert cur.fetchone()[0] == 999999999


def test_superseded_refs_never_carry_an_id(cur):
    cur.execute("""SELECT count(*) FROM futbol.matches
                   WHERE external_ref LIKE '%%superseded%%' AND api_football_fixture_id IS NOT NULL""")
    assert cur.fetchone()[0] == 0


def test_la_liga_duplicates_are_resolved(cur):
    cur.execute("SELECT status FROM futbol.matches WHERE match_id IN (63093, 63094, 63152, 62852)")
    assert {r[0] for r in cur.fetchall()} == {"duplicate"}
    cur.execute("""SELECT api_football_fixture_id, understat_game_id FROM futbol.matches
                   WHERE match_id = 14685""")
    assert cur.fetchone() == (1391139, "29478")


def test_an_understat_row_can_hold_both_ids(cur):
    cur.execute("""SELECT count(*) FROM futbol.matches
                   WHERE understat_game_id IS NOT NULL AND api_football_fixture_id IS NOT NULL""")
    assert cur.fetchone()[0] >= 4
