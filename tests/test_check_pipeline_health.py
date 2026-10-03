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


# --- Slate invariants (ADR-012) -------------------------------------
# The 2026-09-06 NFL freeze passed the staleness check every day:
# nfl_slate:2026 "succeeded" while writing 0 rows for four weeks. These
# check the ledger itself instead of job status.

from check_pipeline_health import MISSING_SLATE_SQL, OUT_OF_WINDOW_SQL  # noqa: E402


def _unslated_match_kicking_off_soon(cur):
    cur.execute(
        """SELECT m.match_id FROM futbol.matches m
           JOIN futbol.seasons s ON s.season_id = m.season_id
           JOIN futbol.leagues l ON l.league_id = s.league_id
           WHERE l.code = 'NFL' AND m.status = 'scheduled'
             AND m.kickoff_utc > now() + interval '10 days'
             AND NOT EXISTS (SELECT 1 FROM futbol.predictions p WHERE p.match_id = m.match_id)
           LIMIT 1""")
    row = cur.fetchone()
    if row is None:
        pytest.skip("no unslated future NFL match to test against")
    return row[0]


def test_missing_slate_flags_an_unslated_fixture_inside_48h(conn):
    cur = conn.cursor()
    match_id = _unslated_match_kicking_off_soon(cur)
    cur.execute("UPDATE futbol.matches SET kickoff_utc = now() + interval '20 hours' WHERE match_id = %s",
                (match_id,))
    cur.execute(MISSING_SLATE_SQL)
    assert match_id in [r[0] for r in cur.fetchall()]


def test_missing_slate_ignores_fixtures_outside_48h(conn):
    cur = conn.cursor()
    match_id = _unslated_match_kicking_off_soon(cur)
    cur.execute(MISSING_SLATE_SQL)
    assert match_id not in [r[0] for r in cur.fetchall()]


def test_out_of_window_flags_a_prediction_locked_weeks_early(conn):
    cur = conn.cursor()
    match_id = _unslated_match_kicking_off_soon(cur)
    cur.execute("SELECT model_version_id FROM futbol.model_versions LIMIT 1")
    mvid = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO futbol.predictions
               (match_id, model_version_id, market, statement, side, probability, created_at, locked_at)
           VALUES (%s, %s, 'MONEYLINE', 'test -- out of window', 'home', 0.6, now(), now())""",
        (match_id, mvid))
    cur.execute(OUT_OF_WINDOW_SQL)
    assert match_id in [r[0] for r in cur.fetchall()]


# --- Duplicate matches (ADR-015) --------------------------------------
# The 2025-26 La Liga Understat load left 4 duplicate match pairs that
# sat unnoticed for months; this catches the next one the night it lands.

from check_pipeline_health import DUPLICATE_MATCH_SQL  # noqa: E402


def test_no_unresolved_duplicates_today(conn):
    cur = conn.cursor()
    cur.execute(DUPLICATE_MATCH_SQL)
    assert cur.fetchall() == []


def test_flags_a_fresh_duplicate(conn):
    cur = conn.cursor()
    cur.execute(
        """SELECT m.match_id, m.season_id, m.home_team_id, m.away_team_id, m.kickoff_utc
           FROM futbol.matches m JOIN futbol.seasons s USING (season_id)
           JOIN futbol.leagues l USING (league_id)
           WHERE l.code = 'EPL' AND m.status = 'final' LIMIT 1""")
    match_id, season_id, home, away, kickoff = cur.fetchone()
    cur.execute(
        """INSERT INTO futbol.matches (season_id, home_team_id, away_team_id, kickoff_utc, status)
           VALUES (%s, %s, %s, %s + interval '1 hour', 'final')""",
        (season_id, home, away, kickoff))
    cur.execute(DUPLICATE_MATCH_SQL)
    assert match_id in [r[0] for r in cur.fetchall()]
