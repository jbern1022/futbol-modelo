"""
Regression test for log_degenerate_candidates() (src/predictions/generator.py)
and the degenerate_prediction_skips table it writes to (sql/migrations/
0008_degenerate_prediction_skips.sql). Closes a product question raised
twice in Todoist: build_slate() silently drops any candidate whose
probability rounds to exactly 0 or 1 (a real, necessary guard against a
predictions.probability CHECK-constraint violation), but did so with
zero visibility -- this is what makes that no longer silent.

Requires migration 0008 to actually be applied against FUTBOL_DSN first
(`python scripts/migrate.py`) -- without it, this fails rather than
skips, which is the point.

Inserts inside one transaction that's always rolled back -- nothing
this test does is ever visible outside it.
"""
import os

import psycopg2
import pytest

from predictions.generator import Inference, log_degenerate_candidates

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def _any_match_id(cur):
    cur.execute("SELECT match_id FROM futbol.matches LIMIT 1")
    row = cur.fetchone()
    if row is None:
        pytest.skip("no match row to attach the test skip to")
    return row[0]


def test_degenerate_candidate_is_logged_and_dropped(conn):
    cur = conn.cursor()
    match_id = _any_match_id(cur)

    candidates = [
        Inference(market="1X2", statement="test — degenerate", line=None,
                  side="home", probability=0.0),
        Inference(market="BTTS", statement="test — valid", line=None,
                  side="yes", probability=0.6),
    ]

    valid = log_degenerate_candidates(cur, match_id, candidates, verbose=False)

    assert [c.statement for c in valid] == ["test — valid"]

    cur.execute(
        """SELECT market, side, raw_probability
           FROM futbol.degenerate_prediction_skips
           WHERE match_id = %s AND statement = %s""",
        (match_id, "test — degenerate"))
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "1X2"
    assert row[1] == "home"
    assert row[2] == 0.0


def test_non_degenerate_candidates_are_not_logged(conn):
    cur = conn.cursor()
    match_id = _any_match_id(cur)

    candidates = [
        Inference(market="BTTS", statement="test — also valid", line=None,
                  side="yes", probability=0.6),
    ]

    valid = log_degenerate_candidates(cur, match_id, candidates, verbose=False)

    assert len(valid) == 1
    cur.execute(
        """SELECT COUNT(*) FROM futbol.degenerate_prediction_skips
           WHERE match_id = %s AND statement = %s""",
        (match_id, "test — also valid"))
    assert cur.fetchone()[0] == 0
