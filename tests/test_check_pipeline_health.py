"""
Regression test for the staleness-detection query in
scripts/check_pipeline_health.py (LAST_SUCCESS_SQL) -- closes the
ntfy half of the "Error handling and ntfy alerting" ticket.

Verified against synthetic pipeline_runs rows for a fabricated job
name (not one of the real EXPECTED_JOBS), inside a transaction that's
always rolled back.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from check_pipeline_health import LAST_SUCCESS_SQL

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def test_returns_most_recent_success_only(conn):
    cur = conn.cursor()
    now = datetime.now(timezone.utc)

    for started, finished, status in [
        (now - timedelta(hours=50), now - timedelta(hours=49), "success"),
        (now - timedelta(hours=30), now - timedelta(hours=29), "failed"),
        (now - timedelta(hours=10), now - timedelta(hours=9), "success"),
    ]:
        cur.execute(
            """INSERT INTO futbol.pipeline_runs (job_name, started_at, finished_at, status)
               VALUES ('test_pipeline_job', %s, %s, %s)""",
            (started, finished, status))

    cur.execute(LAST_SUCCESS_SQL, (["test_pipeline_job"],))
    result = dict(cur.fetchall())

    assert "test_pipeline_job" in result
    # Most recent success was 9h ago, not the failed run at 29h or the
    # older success at 49h.
    age_hours = (now - result["test_pipeline_job"]).total_seconds() / 3600
    assert 8.9 < age_hours < 9.1


def test_job_with_no_success_is_excluded(conn):
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    cur.execute(
        """INSERT INTO futbol.pipeline_runs (job_name, started_at, finished_at, status)
           VALUES ('test_pipeline_job_2', %s, %s, 'failed')""",
        (now - timedelta(hours=5), now - timedelta(hours=4)))

    cur.execute(LAST_SUCCESS_SQL, (["test_pipeline_job_2"],))
    result = dict(cur.fetchall())

    assert "test_pipeline_job_2" not in result
