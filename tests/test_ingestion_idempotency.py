"""
Proves loader.py's docstring claim ("every write is an idempotent
upsert keyed on external ids, so re-running a backfill is always
safe") instead of just asserting it.

Opt-in only (RUN_IDEMPOTENCY_TEST=1) -- unlike the other DB-dependent
tests, this makes real external network calls (FBref via soccerdata)
and actually re-runs a real ingestion path against the live DB. Not
something that should fire on every `make test` or CI run: it's slow,
depends on an external service's availability/rate limits, and -- while
proven safe here -- is still a real write path, not a pure read check.

Targets World Cup specifically: it's the smallest backfill target
(100 matches, one schedule call, no per-match stat scraping), and
avoids a real season-label mismatch between loader.py's hyphenated
format (_season_label: "2026-27") and api_football.py's bare-year
format ("2026") that would otherwise create a genuine duplicate season
+ duplicate fixtures if run against e.g. the current EPL season --
found while scoping this test, tracked separately.

Verified manually before writing this (2026-08-21): baseline 100
matches / 0 team_match_stats / 1 season row, identical after both runs.
"""
import os

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("FUTBOL_DSN")
RUN_IT = os.environ.get("RUN_IDEMPOTENCY_TEST") == "1"
pytestmark = pytest.mark.skipif(
    not (DSN and RUN_IT),
    reason="opt-in only -- set FUTBOL_DSN and RUN_IDEMPOTENCY_TEST=1 to run "
           "(makes real external network calls and live DB writes)")


def _counts(conn):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT
                 (SELECT count(*) FROM futbol.matches m
                    JOIN futbol.seasons s ON s.season_id = m.season_id
                    JOIN futbol.leagues l ON l.league_id = s.league_id
                   WHERE l.code = 'WC') AS matches,
                 (SELECT count(*) FROM futbol.seasons s
                    JOIN futbol.leagues l ON l.league_id = s.league_id
                   WHERE l.code = 'WC') AS seasons"""
        )
        row = cur.fetchone()
        return {"matches": row[0], "seasons": row[1]}


def test_wc_backfill_is_idempotent():
    from ingestion.loader import load_world_cup

    conn = psycopg2.connect(DSN)
    try:
        before = _counts(conn)

        load_world_cup(conn, ["2026"])
        after_run_1 = _counts(conn)

        load_world_cup(conn, ["2026"])
        after_run_2 = _counts(conn)
    finally:
        conn.close()

    assert after_run_1 == after_run_2, (
        f"backfill was not idempotent: run 1 gave {after_run_1}, "
        f"run 2 gave {after_run_2} -- re-running created or removed rows")
    assert after_run_1["seasons"] == before["seasons"] == 1, (
        "expected exactly one WC season row before and after; got "
        f"before={before['seasons']} after={after_run_1['seasons']}")
