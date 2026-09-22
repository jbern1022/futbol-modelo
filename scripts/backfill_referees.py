"""
One-off historical referee backfill (Todoist: "futbol-modelo:
referee-tendencies feature for CARDS market"). backfill()'s ongoing
nightly referee capture (added alongside this script) only covers
whichever season the CronJob currently passes --season for; every
earlier season already in the DB needs this run once to fill in.

Cheap by construction: one bulk /fixtures?league=&season=&status=FT
call per league-season (the exact same call backfill() already makes),
not one call per fixture -- referee was already arriving in that
payload and being silently discarded.

    python scripts/backfill_referees.py --league EPL --league SERIE_A
"""
import argparse
import logging
import os
import sys

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ingestion.api_football import (
    _get, _normalize_referee, _session, find_match_id, resolve_league_id, resolve_team_id,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")


def backfill_referees_for_season(cur, session, league_code: str, season_start_year: int) -> tuple[int, int]:
    league_id = resolve_league_id(session, league_code)

    fixtures = _get(session, "fixtures",
                    {"league": league_id, "season": season_start_year, "status": "FT"})
    updated, skipped = 0, 0
    for fx in fixtures:
        referee = _normalize_referee(fx["fixture"].get("referee"))
        if not referee:
            skipped += 1
            continue
        date = fx["fixture"]["date"][:10]
        home_api_id = fx["teams"]["home"]["id"]
        away_api_id = fx["teams"]["away"]["id"]
        home_id = resolve_team_id(cur, home_api_id, fx["teams"]["home"]["name"])
        away_id = resolve_team_id(cur, away_api_id, fx["teams"]["away"]["name"])
        if not home_id or not away_id:
            skipped += 1
            continue
        match_id = find_match_id(cur, home_id, away_id, date, league_code)
        if not match_id:
            skipped += 1
            continue
        cur.execute(
            "UPDATE futbol.matches SET referee = %s WHERE match_id = %s AND referee IS NULL",
            (referee, match_id))
        updated += cur.rowcount
    return updated, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", action="append", required=True, choices=["EPL", "SERIE_A"])
    ap.add_argument("--seasons", nargs="+", default=None,
                     help="Season labels to backfill, e.g. 2021-22 2022-23. "
                          "Defaults to every season already in the DB for that league.")
    args = ap.parse_args()

    session = _session()
    conn = psycopg2.connect(DSN)
    total_updated = total_skipped = 0
    try:
        with conn.cursor() as cur:
            for league_code in args.league:
                if args.seasons:
                    season_labels = args.seasons
                else:
                    cur.execute(
                        """SELECT DISTINCT s.label FROM futbol.seasons s
                           JOIN futbol.leagues l USING (league_id)
                           WHERE l.code = %s ORDER BY s.label""",
                        (league_code,))
                    season_labels = [r[0] for r in cur.fetchall()]

                for label in season_labels:
                    season_start_year = int(label[:4])
                    updated, skipped = backfill_referees_for_season(
                        cur, session, league_code, season_start_year)
                    conn.commit()
                    total_updated += updated
                    total_skipped += skipped
                    log.info("%s %s: %d referees updated, %d skipped",
                             league_code, label, updated, skipped)
    finally:
        conn.close()
    log.info("done: %d total referees updated, %d skipped", total_updated, total_skipped)


if __name__ == "__main__":
    main()
