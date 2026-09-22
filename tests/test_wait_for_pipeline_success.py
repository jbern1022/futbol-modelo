"""
Regression test for scripts/wait_for_pipeline_success.py's
get_last_success() -- the query the CronJob dependency gate uses to
decide whether an upstream job has actually succeeded recently.

Verified against synthetic pipeline_runs rows for fabricated job names,
inside a transaction that's always rolled back.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from wait_for_pipeline_success import get_last_success

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def test_exact_job_name_returns_most_recent_success(conn):
    cur = conn.cursor()
    now = datetime.now(timezone.utc)

    for started, finished, status in [
        (now - timedelta(hours=5), now - timedelta(hours=4), "success"),
        (now - timedelta(hours=1), now - timedelta(minutes=50), "failed"),
    ]:
        cur.execute(
            """INSERT INTO futbol.pipeline_runs (job_name, started_at, finished_at, status)
               VALUES ('test_gate_job', %s, %s, %s)""",
            (started, finished, status))

    result = get_last_success(cur, job_name="test_gate_job")
    age_hours = (now - result).total_seconds() / 3600
    assert 3.9 < age_hours < 4.1


def test_job_prefix_matches_seasoned_job_names(conn):
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    cur.execute(
        """INSERT INTO futbol.pipeline_runs (job_name, started_at, finished_at, status)
           VALUES ('test_gate_slate:2026-27', %s, %s, 'success')""",
        (now - timedelta(minutes=20), now - timedelta(minutes=15)))

    result = get_last_success(cur, job_prefix="test_gate_slate:")
    age_minutes = (now - result).total_seconds() / 60
    assert 14.5 < age_minutes < 15.5


def test_no_success_returns_none(conn):
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    cur.execute(
        """INSERT INTO futbol.pipeline_runs (job_name, started_at, finished_at, status)
           VALUES ('test_gate_job_never', %s, %s, 'failed')""",
        (now - timedelta(hours=1), now - timedelta(minutes=55)))

    assert get_last_success(cur, job_name="test_gate_job_never") is None
