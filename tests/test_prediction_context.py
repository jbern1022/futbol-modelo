"""
Regression test for persist_slate() writing Inference.context to the new
predictions.context JSONB column (the "why" panel's backing data).
Covers the NaN edge case specifically: current_form()'s rolling .mean()
can return NaN on a sparse data window, and json.dumps emits a literal
(invalid) NaN token that Postgres's JSONB parser rejects -- _sanitize_context
is what's supposed to catch that before it reaches the INSERT. Runs
against the live DB in an explicit transaction that's always rolled
back -- skips cleanly without FUTBOL_DSN.

persist_slate() calls conn.commit() internally, which would otherwise
make this test's insert permanent before the fixture's own rollback()
ever runs (a real bug this test used to have -- see Todoist).
_CommitSuppressingConn proxies the real connection but no-ops commit(),
so persist_slate() runs unmodified and unaware, and the fixture's
rollback() at teardown is the only thing that actually ends the
transaction.
"""
import datetime
import math
import os

import psycopg2
import pytest

from predictions.generator import Inference, persist_slate

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


class _CommitSuppressingConn:
    """Delegates everything to a real connection except commit(), which is
    a no-op -- lets persist_slate() run exactly as it does in production
    while leaving the test's own transaction open for a real rollback."""

    def __init__(self, real_conn):
        self._real = real_conn

    def cursor(self, *args, **kwargs):
        return self._real.cursor(*args, **kwargs)

    def commit(self):
        pass


def test_context_persists_and_nan_is_sanitized(conn):
    cur = conn.cursor()
    cur.execute(
        """SELECT match_id, home_team_id FROM futbol.matches
           WHERE kickoff_utc > now() LIMIT 1""")
    match_id, team_id = cur.fetchone()
    cur.execute("SELECT model_version_id FROM futbol.model_versions LIMIT 1")
    row = cur.fetchone()
    if row is None:
        pytest.skip("no model_versions row to attach the test prediction to")
    model_version_id = row[0]

    slate = [
        Inference(
            market="CORNERS", statement="test — Corners over 3.5", line=3.5,
            side="over", probability=0.7, subject_team_id=team_id,
            context={"corners_for_r5": 5.2, "rest_days": 6, "xg_for_r5": float("nan")},
        )
    ]
    persist_slate(_CommitSuppressingConn(conn), match_id, model_version_id, slate)

    cur.execute(
        """SELECT context FROM futbol.predictions
           WHERE match_id = %s AND statement = %s""",
        (match_id, "test — Corners over 3.5"))
    context = cur.fetchone()[0]

    assert context["corners_for_r5"] == 5.2
    assert context["rest_days"] == 6
    assert context["xg_for_r5"] is None, "NaN should have been sanitized to null, not left as NaN"
