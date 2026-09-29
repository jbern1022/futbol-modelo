"""
ADR-010's close-to-kickoff final pass, batch entry point -- finds every
fixture kicking off within the next `--hours-ahead` window that already
has an original PLAYER_GOALS/PLAYER_SAVES slate but no final pass yet,
and generates one. Reuses generate_final_pass_for_fixture so behavior
is identical whether triggered by hand or by the CronJob.

Meant to run frequently (every 15-30 min, see k8s/cronjobs.yaml's
futbol-props-final-pass) -- the query below is cheap (a handful of
fixtures at most, across 4 leagues, at any given 15-30 min tick).

    python scripts/auto_final_pass.py --league MLS --hours-ahead 2
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import psycopg2

from generate_slate import generate_final_pass_for_fixture, PLAYER_PROPS_LEAGUES
from ops.json_logging import configure_json_logging
from ops.pipeline_run import track_run

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# "Has an original slate" = any prediction at all for this match_id
# (every original slate includes 1X2, so this is a safe proxy without
# assuming PLAYER_GOALS/PLAYER_SAVES specifically fired for it).
# "No final pass yet" = no prediction under the distinct
# player_props_lineup_confirmed_v1 model_version -- see ADR-010.
NEEDS_FINAL_PASS_SQL = """
SELECT m.match_id, m.kickoff_utc, th.name AS home, ta.name AS away,
       m.home_team_id, m.away_team_id
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
WHERE l.code = %s
  AND m.status = 'scheduled'
  AND m.kickoff_utc BETWEEN now() AND now() + (%s || ' hours')::interval
  AND EXISTS (SELECT 1 FROM futbol.predictions p WHERE p.match_id = m.match_id)
  AND NOT EXISTS (
      SELECT 1 FROM futbol.predictions p2
      JOIN futbol.model_versions mv ON mv.model_version_id = p2.model_version_id
      WHERE p2.match_id = m.match_id
        AND mv.model_name = 'player_props_lineup_confirmed_v1')
ORDER BY m.kickoff_utc;
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=sorted(PLAYER_PROPS_LEAGUES))
    ap.add_argument("--hours-ahead", type=float, default=2,
                    help="Fixtures kicking off within this many hours (default 2)")
    args = ap.parse_args()
    log = configure_json_logging(f"auto_final_pass:{args.league}")

    with track_run(f"auto_final_pass:{args.league}") as set_rows_written:
        conn = psycopg2.connect(DSN)
        with conn.cursor() as cur:
            cur.execute(NEEDS_FINAL_PASS_SQL, (args.league, args.hours_ahead))
            fixtures = cur.fetchall()
            log.info("fixtures needing a final pass", extra={
                "league": args.league, "n_fixtures": len(fixtures),
                "hours_ahead": args.hours_ahead,
            })

            written = 0
            for match_id, kickoff, home, away, home_id, away_id in fixtures:
                # Same isolation as auto_slate.py -- one fixture's failure
                # (e.g. a real API-Football hiccup mid-poll) must not take
                # the rest of this run's fixtures down with it.
                try:
                    n = generate_final_pass_for_fixture(
                        conn, cur, args.league, home, away,
                        match_id, kickoff, home_id, away_id)
                except Exception:
                    conn.rollback()
                    log.error("final pass failed, skipping (others unaffected)",
                             extra={"league": args.league, "home": home, "away": away},
                             exc_info=True)
                    continue
                if n:
                    written += n

        conn.close()
        set_rows_written(written)
        log.info("auto_final_pass done", extra={
            "league": args.league, "n_fixtures_processed": len(fixtures),
            "n_predictions_written": written,
        })


if __name__ == "__main__":
    main()
