"""
Fill futbol.team_fixtures (migration 0042): every competitive fixture each
team in a league played, across all competitions, from API-Football's
/fixtures?team=&season= (one call per team-season). Friendlies skipped.
Idempotent (upsert on team + fixture).

    python scripts/backfill_team_fixtures.py --league EPL --seasons 2021-22 2022-23
    python scripts/backfill_team_fixtures.py --league MLS --seasons 2025
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2

from ingestion.api_football import _get, _session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

TEAMS_SQL = """
SELECT DISTINCT t.team_id, t.api_football_id
FROM futbol.matches m
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.teams t ON t.team_id IN (m.home_team_id, m.away_team_id)
WHERE l.code = %s AND s.label = %s AND t.api_football_id IS NOT NULL
"""


def is_competitive(fx: dict) -> bool:
    return "friendl" not in (fx["league"].get("name") or "").lower()


def rows_for_team(team_id: int, api_team_id: int, fixtures: list[dict]) -> list[tuple]:
    return [(team_id, fx["fixture"]["id"], fx["fixture"]["date"], fx["league"]["name"],
             fx["league"]["id"], fx["teams"]["home"]["id"] == api_team_id,
             fx["fixture"]["status"]["short"])
            for fx in fixtures if is_competitive(fx)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    ap.add_argument("--seasons", nargs="+", required=True, help="our season labels, e.g. 2024-25 or 2025")
    args = ap.parse_args()
    session = _session()
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        for label in args.seasons:
            cur.execute(TEAMS_SQL, (args.league, label))
            teams = cur.fetchall()
            stored = 0
            for team_id, api_team_id in teams:
                fixtures = _get(session, "fixtures", {"team": api_team_id, "season": int(label[:4])})
                rows = rows_for_team(team_id, api_team_id, fixtures)
                cur.executemany(
                    """INSERT INTO futbol.team_fixtures
                         (team_id, api_fixture_id, kickoff_utc, competition, api_league_id, is_home, status_short)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (team_id, api_fixture_id) DO UPDATE SET
                         kickoff_utc = EXCLUDED.kickoff_utc, status_short = EXCLUDED.status_short,
                         fetched_at = now()""", rows)
                stored += len(rows)
            conn.commit()
            log.info("%s %s: %d teams, %d competitive fixtures", args.league, label, len(teams), stored)
    conn.close()


if __name__ == "__main__":
    main()
