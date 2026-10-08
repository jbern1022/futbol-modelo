"""
One-off historical player_match_stats backfill (Todoist: "backfill player
match stats for EPL 2023-25 and Serie A 2021-26", data audit 2026-10-03).

player_match_stats is empty for EPL 2023-24 / 2024-25 and for every Serie A
season before 2026-27, so the PLAYER_GOALS / PLAYER_SAVES models have no
Serie A history and a two-season EPL hole. Every historical EPL/SERIE_A
match carries api_football_fixture_id (ADR-015), so /fixtures/players can
fill it: one call per fixture (~380 per league-season).

Reuses load_fixture_players() -- the exact function the nightly refresh
used to write the 2026-27 rows -- so backfilled rows are written the same
way as live ones. Only matches with NO player_match_stats rows yet are
selected, so the run is resumable and never rewrites existing rows.

Dry run by default: reads counts only, makes no API calls and no writes.

    python scripts/backfill_player_match_stats.py --league EPL --seasons 2023-24 2024-25
    python scripts/backfill_player_match_stats.py --league SERIE_A --seasons 2021-22 --limit 5 --execute
    python scripts/backfill_player_match_stats.py --league SERIE_A --execute   # every empty season

Stops after --max-consecutive-failures failed fixtures in a row (default
5), so an exhausted daily quota doesn't burn through the rest of the list.
"""
import argparse
import logging
import os
import sys
from collections import Counter

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ingestion.api_football import _session, load_fixture_players

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

LEAGUES = ("EPL", "SERIE_A")
COMMIT_EVERY = 20

PENDING_SQL = """
SELECT m.match_id, m.api_football_fixture_id, m.home_team_id, m.away_team_id,
       th.api_football_id, s.label
FROM futbol.matches m
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.teams th ON th.team_id = m.home_team_id
WHERE l.code = %s
  AND m.status = 'final'
  AND m.api_football_fixture_id IS NOT NULL
  AND th.api_football_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM futbol.player_match_stats p WHERE p.match_id = m.match_id)
  {season_filter}
ORDER BY m.kickoff_utc
"""


def pending_matches(cur, league_code: str, season_labels: list[str] | None) -> list[tuple]:
    season_filter = "AND s.label = ANY(%s)" if season_labels else ""
    params: list = [league_code]
    if season_labels:
        params.append(season_labels)
    cur.execute(PENDING_SQL.format(season_filter=season_filter), params)
    return cur.fetchall()


def run_backfill(conn, session, rows: list[tuple], load=load_fixture_players,
                 max_consecutive_failures: int = 5) -> tuple[int, int, bool]:
    """Returns (loaded, failed, aborted). `load` is injectable for tests."""
    loaded = failed = consecutive = 0
    for i, (match_id, fixture_id, home_id, away_id, home_api_id, _label) in enumerate(rows, 1):
        try:
            with conn.cursor() as cur:
                load(session, cur, match_id, fixture_id, home_id, away_id, home_api_id)
            loaded += 1
            consecutive = 0
        except Exception:
            conn.rollback()
            failed += 1
            consecutive += 1
            log.warning("fixture %d (match_id %d) failed", fixture_id, match_id, exc_info=True)
            if consecutive >= max_consecutive_failures:
                log.error("%d failures in a row -- stopping (quota or outage?); rerun to resume",
                          consecutive)
                conn.commit()
                return loaded, failed, True
            continue
        if i % COMMIT_EVERY == 0:
            conn.commit()
            log.info("progress: %d/%d fixtures", i, len(rows))
    conn.commit()
    return loaded, failed, False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", action="append", required=True, choices=LEAGUES)
    ap.add_argument("--seasons", nargs="+", default=None,
                    help="Season labels, e.g. 2023-24 2024-25. Default: every season with gaps.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process at most this many fixtures per league (pilot runs).")
    ap.add_argument("--max-consecutive-failures", type=int, default=5)
    ap.add_argument("--execute", action="store_true",
                    help="call API-Football and write rows (default: dry run, counts only)")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    session = _session() if args.execute else None
    try:
        for league_code in args.league:
            with conn.cursor() as cur:
                rows = pending_matches(cur, league_code, args.seasons)
            by_season = Counter(r[5] for r in rows)
            print(f"{league_code}: {len(rows)} fixture(s) with no player stats "
                  f"(= {len(rows)} API calls)")
            for label in sorted(by_season):
                print(f"  {label}: {by_season[label]}")
            if args.limit:
                rows = rows[:args.limit]
            if not args.execute:
                continue
            loaded, failed, aborted = run_backfill(
                conn, session, rows, max_consecutive_failures=args.max_consecutive_failures)
            print(f"{league_code}: loaded {loaded}, failed {failed}"
                  f"{' -- ABORTED early' if aborted else ''}")
            if aborted:
                break
        if not args.execute:
            conn.rollback()
            print("\ndry run -- no API calls, nothing written (pass --execute to run)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
