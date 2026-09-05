"""
Batch slate generation — finds every upcoming fixture (within N days,
in a supported league) that doesn't have a slate yet, and generates one.
Reuses generate_for_fixture from generate_slate.py so behavior is
identical whether triggered by hand or automatically.

    python scripts/auto_slate.py --league MLS --days 7
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import psycopg2

from generate_slate import generate_for_fixture, PROPS_LEAGUES
from ops.pipeline_run import track_run

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

UPCOMING_UNSLATED_SQL = """
SELECT m.match_id, m.kickoff_utc, th.name AS home, ta.name AS away,
       m.home_team_id, m.away_team_id
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
LEFT JOIN futbol.predictions p ON p.match_id = m.match_id
WHERE l.code = %s
  AND m.status = 'scheduled'
  AND m.kickoff_utc BETWEEN now() AND now() + (%s || ' days')::interval
  AND p.prediction_id IS NULL
GROUP BY m.match_id, m.kickoff_utc, th.name, ta.name, m.home_team_id, m.away_team_id
ORDER BY m.kickoff_utc;
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    with track_run(f"auto_slate:{args.league}") as set_rows_written:
        conn = psycopg2.connect(DSN)
        with conn.cursor() as cur:
            cur.execute(UPCOMING_UNSLATED_SQL, (args.league, args.days))
            fixtures = cur.fetchall()
            print(f"[{args.league}] {len(fixtures)} upcoming fixture(s) without a slate "
                  f"(next {args.days} days)")

            written = 0
            for match_id, kickoff, home, away, home_id, away_id in fixtures:
                # One fixture's failure (e.g. a degenerate model output)
                # must not take every other fixture in this batch down
                # with it -- and since this script is && chained with
                # the next league's run in cronjobs.yaml, an uncaught
                # exception here silently skips that league's entire
                # slate too. conn.rollback() clears the aborted
                # transaction state a failed INSERT leaves behind, so
                # the next fixture starts clean. Real incident
                # (2026-08-27): an uncaught CheckViolation on one
                # newly-promoted team's 0.0 win probability killed the
                # rest of EPL's batch and Serie A's run entirely.
                try:
                    n = generate_for_fixture(conn, cur, args.league, home, away,
                                             match_id, kickoff, home_id, away_id)
                except Exception as e:
                    conn.rollback()
                    print(f"  ERROR {home} vs {away}: {e} -- skipping, other fixtures unaffected")
                    continue
                if n:
                    written += n

        conn.close()
        set_rows_written(written)
        print(f"[{args.league}] auto_slate done: {len(fixtures)} fixtures processed, "
              f"{written} total predictions written")


if __name__ == "__main__":
    main()
