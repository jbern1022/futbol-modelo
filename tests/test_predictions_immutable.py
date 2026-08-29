"""
Regression test for the two triggers the entire ledger design rests on
(see README's "ledger discipline" section and ADR-002 in
docs/DECISIONS.md): predictions.forbid_prediction_mutation() rejects
UPDATE/DELETE, and enforce_pre_kickoff() rejects an INSERT locked at or
after kickoff. Until now these were asserted only in prose, never by a
test -- CLAIMS.md is what surfaced the gap.

Inserts via raw SQL, not persist_slate() (which commits internally --
see test_prediction_context.py, which as a result leaves real "test —
..." rows in the live ledger on every run, a separate pre-existing gap
flagged in Todoist rather than fixed here). Everything here runs inside
one transaction, using SAVEPOINTs to survive each trigger's expected
failure without aborting the whole transaction, and is always rolled
back -- nothing this test does is ever visible outside it.
"""
import datetime
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


def _insert_test_prediction(cur, match_id, model_version_id, locked_at):
    cur.execute(
        """INSERT INTO futbol.predictions
               (match_id, model_version_id, market, statement, side,
                probability, created_at, locked_at)
           VALUES (%s, %s, 'BTTS', 'test — immutability check', 'yes',
                   0.5, now(), %s)
           RETURNING prediction_id""",
        (match_id, model_version_id, locked_at))
    return cur.fetchone()[0]


def _future_fixture(cur):
    cur.execute(
        """SELECT match_id, kickoff_utc FROM futbol.matches
           WHERE kickoff_utc > now() LIMIT 1""")
    row = cur.fetchone()
    if row is None:
        pytest.skip("no upcoming fixture to attach the test prediction to")
    return row


def _any_model_version(cur):
    cur.execute("SELECT model_version_id FROM futbol.model_versions LIMIT 1")
    row = cur.fetchone()
    if row is None:
        pytest.skip("no model_versions row to attach the test prediction to")
    return row[0]


def test_update_is_rejected(conn):
    cur = conn.cursor()
    match_id, kickoff = _future_fixture(cur)
    model_version_id = _any_model_version(cur)
    prediction_id = _insert_test_prediction(cur, match_id, model_version_id, datetime.datetime.now(datetime.timezone.utc))

    cur.execute("SAVEPOINT before_update")
    with pytest.raises(psycopg2.errors.RaiseException, match="predictions are immutable"):
        cur.execute(
            "UPDATE futbol.predictions SET probability = 0.9 WHERE prediction_id = %s",
            (prediction_id,))
    cur.execute("ROLLBACK TO SAVEPOINT before_update")


def test_delete_is_rejected(conn):
    cur = conn.cursor()
    match_id, kickoff = _future_fixture(cur)
    model_version_id = _any_model_version(cur)
    prediction_id = _insert_test_prediction(cur, match_id, model_version_id, datetime.datetime.now(datetime.timezone.utc))

    cur.execute("SAVEPOINT before_delete")
    with pytest.raises(psycopg2.errors.RaiseException, match="predictions are immutable"):
        cur.execute("DELETE FROM futbol.predictions WHERE prediction_id = %s", (prediction_id,))
    cur.execute("ROLLBACK TO SAVEPOINT before_delete")


def test_insert_locked_at_or_after_kickoff_is_rejected(conn):
    cur = conn.cursor()
    match_id, kickoff = _future_fixture(cur)
    model_version_id = _any_model_version(cur)

    cur.execute("SAVEPOINT before_late_insert")
    with pytest.raises(psycopg2.errors.RaiseException, match="prediction locked after kickoff"):
        _insert_test_prediction(cur, match_id, model_version_id, kickoff)
    cur.execute("ROLLBACK TO SAVEPOINT before_late_insert")


def test_insert_locked_before_kickoff_succeeds(conn):
    """Sanity check the two rejection tests above aren't vacuously
    passing because every insert fails -- a genuinely valid, pre-kickoff
    insert must go through."""
    cur = conn.cursor()
    match_id, kickoff = _future_fixture(cur)
    model_version_id = _any_model_version(cur)
    prediction_id = _insert_test_prediction(
        cur, match_id, model_version_id, kickoff - datetime.timedelta(hours=1))
    assert prediction_id is not None
