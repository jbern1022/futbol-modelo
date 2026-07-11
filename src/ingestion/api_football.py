"""
API-Football integration — fills the gap FBref left blocked (corners,
cards, saves, shots-on-target, possession). Matches onto the *existing*
matches table (built from Understat) via team name + date, rather than
creating a second, parallel set of match rows.

    python -m ingestion.api_football backfill --league EPL --season 2025
    (API-Football uses the year the season STARTS, e.g. 2025 = 2025-26)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import psycopg2
import requests

log = logging.getLogger("api_football")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BASE_URL = "https://v3.football.api-sports.io"
API_KEY = os.environ.get("API_FOOTBALL_KEY")
DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

LEAGUE_SEARCH = {
    "EPL": ("Premier League", "England"),
    "SERIE_A": ("Serie A", "Italy"),
}

NAME_ALIASES = {
    "AC Milan": "Milan",
    "AS Roma": "Roma",
    "Hellas Verona": "Verona",
    "Inter Milan": "Inter",
    "Internazionale": "Inter",
    "Manchester Utd": "Manchester United",
    "Newcastle Utd": "Newcastle",
    "Nott'm Forest": "Nottingham Forest",
    "Wolverhampton Wanderers": "Wolves",
}

CACHE_FILE = Path.home() / ".api_football_cache.json"


def _session() -> requests.Session:
    if not API_KEY:
        raise SystemExit("API_FOOTBALL_KEY not set — export it first.")
    s = requests.Session()
    s.headers.update({"x-apisports-key": API_KEY})
    return s


def _get(session: requests.Session, endpoint: str, params: dict) -> list:
    resp = session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(f"API-Football error on {endpoint}: {data['errors']}")
    time.sleep(0.3)
    return data.get("response", [])


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def _save_cache(cache: dict):
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def resolve_league_id(session: requests.Session, league_code: str) -> int:
    cache = _load_cache()
    if league_code in cache.get("league_ids", {}):
        return cache["league_ids"][league_code]

    name, country = LEAGUE_SEARCH[league_code]
    results = _get(session, "leagues", {"name": name, "country": country})
    if not results:
        raise RuntimeError(f"No league found for {name} / {country}")
    league_id = results[0]["league"]["id"]

    cache.setdefault("league_ids", {})[league_code] = league_id
    _save_cache(cache)
    log.info("resolved %s -> API-Football league id %d", league_code, league_id)
    return league_id


def resolve_team_id(cur, api_team_id: int, api_team_name: str) -> int | None:
    cur.execute("SELECT team_id FROM futbol.teams WHERE api_football_id = %s",
               (api_team_id,))
    row = cur.fetchone()
    if row:
        return row[0]

    lookup_name = NAME_ALIASES.get(api_team_name, api_team_name)
    cur.execute("SELECT team_id FROM futbol.teams WHERE LOWER(name) = LOWER(%s)",
               (lookup_name,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE futbol.teams SET api_football_id = %s WHERE team_id = %s",
                   (api_team_id, row[0]))
        return row[0]

    log.warning("no match for API-Football team %r (id=%d) — skipping",
               api_team_name, api_team_id)
    return None


def find_match_id(cur, home_team_id: int, away_team_id: int, date: str) -> int | None:
    cur.execute(
        """SELECT match_id FROM futbol.matches
           WHERE home_team_id = %s AND away_team_id = %s
             AND DATE(kickoff_utc) = %s""",
        (home_team_id, away_team_id, date))
    row = cur.fetchone()
    return row[0] if row else None


def backfill(league_code: str, season_start_year: int):
    session = _session()
    league_id = resolve_league_id(session, league_code)

    conn = psycopg2.connect(DSN)
    fixtures = _get(session, "fixtures",
                    {"league": league_id, "season": season_start_year, "status": "FT"})
    log.info("%d completed fixtures from API-Football", len(fixtures))

    updated, skipped_team, skipped_match = 0, 0, 0
    with conn.cursor() as cur:
        for fx in fixtures:
            fixture_id = fx["fixture"]["id"]
            date = fx["fixture"]["date"][:10]
            home_api_id = fx["teams"]["home"]["id"]
            away_api_id = fx["teams"]["away"]["id"]

            home_id = resolve_team_id(cur, home_api_id, fx["teams"]["home"]["name"])
            away_id = resolve_team_id(cur, away_api_id, fx["teams"]["away"]["name"])
            if not home_id or not away_id:
                skipped_team += 1
                continue

            match_id = find_match_id(cur, home_id, away_id, date)
            if not match_id:
                skipped_match += 1
                continue

            stats = _get(session, "fixtures/statistics", {"fixture": fixture_id})
            for team_stats in stats:
                api_tid = team_stats["team"]["id"]
                tid = home_id if api_tid == home_api_id else away_id
                vals = {s["type"]: s["value"] for s in team_stats["statistics"]}

                def num(key):
                    v = vals.get(key)
                    if v is None:
                        return None
                    if isinstance(v, str) and v.endswith("%"):
                        return float(v.rstrip("%"))
                    return v

                cur.execute(
                    """UPDATE futbol.team_match_stats SET
                         corners = %s, fouls = %s, yellows = %s, reds = %s,
                         saves = %s, shots_on_target = %s, shots = %s,
                         possession_pct = %s
                       WHERE match_id = %s AND team_id = %s""",
                    (num("Corner Kicks"), num("Fouls"), num("Yellow Cards"),
                     num("Red Cards"), num("Goalkeeper Saves"),
                     num("Shots on Goal"), num("Total Shots"),
                     num("Ball Possession"), match_id, tid))
            updated += 1
            if updated % 20 == 0:
                conn.commit()
                log.info("progress: %d/%d fixtures updated", updated, len(fixtures))

        conn.commit()
    conn.close()
    log.info("done: %d updated, %d skipped (team match), %d skipped (fixture match)",
             updated, skipped_team, skipped_match)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["backfill"])
    ap.add_argument("--league", required=True, choices=list(LEAGUE_SEARCH))
    ap.add_argument("--season", required=True, type=int,
                    help="Season START year, e.g. 2025 for the 2025-26 season")
    args = ap.parse_args()
    backfill(args.league, args.season)


if __name__ == "__main__":
    main()
