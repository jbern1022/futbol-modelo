"""
Regression test for the prediction_grades immutability trigger added in
sql/migrations/0007_lock_prediction_grades.sql (see CLAIMS.md's "The
ledger" table -- this closes the previously-flagged "Code path only"
gap: a PRIMARY KEY on prediction_id stopped a second INSERT for the
same prediction, but nothing stopped a raw UPDATE from silently
rewriting an existing grade's outcome).

Requires migration 0007 to actually be applied against FUTBOL_DSN first
(`python scripts/migrate.py`) -- without it, these tests fail rather
than skip, which is the point: it should be obvious the lock isn't live
yet, not silently green.

Inserts via raw SQL inside one transaction, using SAVEPOINTs to survive
the trigger's expected failure without aborting the whole transaction,
and is always rolled back -- nothing this test does is ever visible
outside it.
"""
import os

import psycopg2
import psycopg2.errors
import pytest

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def _insert_graded_test_prediction(cur):
    cur.execute(
        """SELECT match_id FROM futbol.matches
           WHERE kickoff_utc > now() LIMIT 1""")
    row = cur.fetchone()
    if row is None:
        pytest.skip("no upcoming fixture to attach the test prediction to")
    match_id = row[0]

    cur.execute("SELECT model_version_id FROM futbol.model_versions LIMIT 1")
    row = cur.fetchone()
    if row is None:
        pytest.skip("no model_versions row to attach the test prediction to")
    model_version_id = row[0]

    cur.execute(
        """INSERT INTO futbol.predictions
               (match_id, model_version_id, market, statement, side,
                probability, created_at, locked_at)
           VALUES (%s, %s, 'BTTS', 'test — grade immutability check', 'yes',
                   0.5, now(), now())
           RETURNING prediction_id""",
        (match_id, model_version_id))
    prediction_id = cur.fetchone()[0]

    cur.execute(
        """INSERT INTO futbol.prediction_grades
               (prediction_id, outcome, actual_value, graded_at, grader_version)
           VALUES (%s, 'hit', 1, now(), 'test')""",
        (prediction_id,))
    return prediction_id


def test_grade_update_is_rejected(conn):
    cur = conn.cursor()
    prediction_id = _insert_graded_test_prediction(cur)

    cur.execute("SAVEPOINT before_update")
    with pytest.raises(psycopg2.errors.RaiseException, match="prediction_grades are immutable"):
        cur.execute(
            "UPDATE futbol.prediction_grades SET outcome = 'miss' WHERE prediction_id = %s",
            (prediction_id,))
    cur.execute("ROLLBACK TO SAVEPOINT before_update")


def test_grade_delete_is_rejected(conn):
    cur = conn.cursor()
    prediction_id = _insert_graded_test_prediction(cur)

    cur.execute("SAVEPOINT before_delete")
    with pytest.raises(psycopg2.errors.RaiseException, match="prediction_grades are immutable"):
        cur.execute("DELETE FROM futbol.prediction_grades WHERE prediction_id = %s", (prediction_id,))
    cur.execute("ROLLBACK TO SAVEPOINT before_delete")
