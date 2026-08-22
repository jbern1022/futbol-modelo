"""
Regression test for persist_slate() writing Inference.context to the new
predictions.context JSONB column (the "why" panel's backing data).
Covers the NaN edge case specifically: current_form()'s rolling .mean()
can return NaN on a sparse data window, and json.dumps emits a literal
(invalid) NaN token that Postgres's JSONB parser rejects -- _sanitize_context
is what's supposed to catch that before it reaches the INSERT. Runs
against the live DB in an explicit transaction that's always rolled
back -- skips cleanly without FUTBOL_DSN.
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
    persist_slate(conn, match_id, model_version_id, slate)

    cur.execute(
        """SELECT context FROM futbol.predictions
           WHERE match_id = %s AND statement = %s""",
        (match_id, "test — Corners over 3.5"))
    context = cur.fetchone()[0]

    assert context["corners_for_r5"] == 5.2
    assert context["rest_days"] == 6
    assert context["xg_for_r5"] is None, "NaN should have been sanitized to null, not left as NaN"
