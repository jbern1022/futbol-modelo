"""
Integration test asserting sql/features.sql's rolling features are
genuinely as-of the match date -- props.py claims this in a comment
("All features are AS-OF the match date (no leakage; enforce in SQL)")
with nothing that actually checks it. Needs a live DB (FUTBOL_DSN);
skips cleanly without one rather than failing CI/dev environments that
don't have the homelab Postgres reachable.
"""
import os

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture(scope="module")
def conn():
    c = psycopg2.connect(DSN, cursor_factory=psycopg2.extras.RealDictCursor)
    yield c
    c.close()


def test_n_prior_never_counts_current_or_future_matches(conn):
    """n_prior should equal LEAST(10, count of that team's strictly-earlier
    finalized matches). If the window frame ever included the current row
    or a future one (an off-by-one in the ROWS BETWEEN clause, e.g.), this
    would be inflated relative to the independently-recomputed count."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT tmf.match_id, tmf.team_id, tmf.n_prior, tmf.kickoff_utc,
                      LEAST(10, (SELECT COUNT(*) FROM futbol.team_match_features x
                                 WHERE x.team_id = tmf.team_id
                                   AND x.kickoff_utc < tmf.kickoff_utc)) AS true_prior_count
               FROM futbol.team_match_features tmf
               ORDER BY random() LIMIT 500"""
        )
        rows = cur.fetchall()
    assert rows, "team_match_features is empty -- run sql/features.sql first"
    mismatches = [r for r in rows if r["n_prior"] != r["true_prior_count"]]
    assert not mismatches, f"n_prior leaked future/current data on {len(mismatches)} rows: {mismatches[:5]}"


def test_corners_for_r5_matches_independent_recomputation(conn):
    """Cross-checks the materialized rolling average itself (not just the
    row count) against a plain correlated-subquery recomputation that
    bypasses the window function entirely, for a random sample."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT match_id, team_id, kickoff_utc, corners_for_r5
               FROM futbol.team_match_features
               WHERE corners_for_r5 IS NOT NULL
               ORDER BY random() LIMIT 30"""
        )
        sample = cur.fetchall()
        assert sample, "no rows with a populated corners_for_r5 to sample"

        mismatches = []
        for row in sample:
            cur.execute(
                """SELECT AVG(corners) AS recomputed FROM (
                     SELECT s.corners
                     FROM futbol.team_match_stats s
                     JOIN futbol.matches m USING (match_id)
                     WHERE s.team_id = %s AND m.status = 'final'
                       AND m.kickoff_utc < %s
                     ORDER BY m.kickoff_utc DESC LIMIT 5
                   ) recent""",
                (row["team_id"], row["kickoff_utc"]))
            recomputed = cur.fetchone()["recomputed"]
            if recomputed is None or abs(float(recomputed) - float(row["corners_for_r5"])) > 1e-6:
                mismatches.append((row["match_id"], row["team_id"], row["corners_for_r5"], recomputed))
    assert not mismatches, f"corners_for_r5 disagreed with independent recomputation: {mismatches}"
