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
    "MLS": ("Major League Soccer", "USA"),
    "LA_LIGA": ("La Liga", "Spain"),
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
    "Leeds": "Leeds United",
    "Leicester": "Leicester City",
    "Norwich": "Norwich City",
    "Luton": "Luton Town",
    "Sheffield Utd": "Sheffield United",
    "Ipswich": "Ipswich Town",
    "Oviedo": "Real Oviedo",
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
        log.info("no match for %r/%r, retrying name-only search", name, country)
        results = _get(session, "leagues", {"search": name})
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
    """+/-1 day tolerance: sources occasionally disagree on which
    calendar day a match falls on across a UTC boundary."""
    cur.execute(
        """SELECT match_id FROM futbol.matches
           WHERE home_team_id = %s AND away_team_id = %s
             AND DATE(kickoff_utc) BETWEEN %s::date - 1 AND %s::date + 1
           ORDER BY ABS(DATE(kickoff_utc) - %s::date) LIMIT 1""",
        (home_team_id, away_team_id, date, date, date))
    row = cur.fetchone()
    return row[0] if row else None


def resolve_or_create_team_id(cur, api_team_id: int, api_team_name: str) -> int:
    """Like resolve_team_id, but creates a new team row if none exists —
    needed for MLS, where there's no prior Understat-sourced team list
    to match against. Relies on the teams.name UNIQUE constraint."""
    cur.execute("SELECT team_id FROM futbol.teams WHERE api_football_id = %s",
               (api_team_id,))
    row = cur.fetchone()
    if row:
        return row[0]

    lookup_name = NAME_ALIASES.get(api_team_name, api_team_name)
    cur.execute(
        """INSERT INTO futbol.teams (name, api_football_id) VALUES (%s, %s)
           ON CONFLICT (name) DO UPDATE SET api_football_id = EXCLUDED.api_football_id
           RETURNING team_id""",
        (lookup_name, api_team_id))
    return cur.fetchone()[0]


def upsert_league_season(cur, league_code: str, league_name: str, season_label: str):
    cur.execute(
        """INSERT INTO futbol.leagues (code, name) VALUES (%s, %s)
           ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
           RETURNING league_id""", (league_code, league_name))
    league_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO futbol.seasons (league_id, label) VALUES (%s, %s)
           ON CONFLICT (league_id, label) DO UPDATE SET label = EXCLUDED.label
           RETURNING season_id""", (league_id, season_label))
    return cur.fetchone()[0]


def resolve_or_create_player_id(cur, api_player_id: int, player_name: str,
                                position: str | None = None) -> int:
    """Player identity is resolved purely by api_football_id (no name-based
    conflict resolution, unlike teams — player names collide legitimately
    all the time; the numeric id is the only safe key)."""
    cur.execute(
        """INSERT INTO futbol.players (full_name, position, api_football_id)
           VALUES (%s, %s, %s)
           ON CONFLICT (api_football_id) DO UPDATE SET full_name = EXCLUDED.full_name
           RETURNING player_id""",
        (player_name, position, api_player_id))
    return cur.fetchone()[0]


def load_fixture_players(session, cur, match_id: int, fixture_id: int,
                         home_id: int, away_id: int, home_api_id: int):
    """Pull per-player stats for one finished fixture (fixtures/players)
    and populate player_match_stats."""
    resp = _get(session, "fixtures/players", {"fixture": fixture_id})
    for team_block in resp:
        api_tid = team_block["team"]["id"]
        tid = home_id if api_tid == home_api_id else away_id
        for p in team_block["players"]:
            stats = p["statistics"][0] if p["statistics"] else {}
            games = stats.get("games", {}) or {}
            shots = stats.get("shots", {}) or {}
            goals = stats.get("goals", {}) or {}
            passes = stats.get("passes", {}) or {}

            minutes = games.get("minutes")
            if minutes is None or minutes == 0:
                continue

            pid = resolve_or_create_player_id(
                cur, p["player"]["id"], p["player"]["name"], games.get("position"))

            cur.execute(
                """INSERT INTO futbol.player_match_stats
                     (match_id, player_id, team_id, minutes, goals, assists,
                      shots, shots_on_target, key_passes, saves, goals_conceded)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (match_id, player_id) DO UPDATE SET
                     minutes = EXCLUDED.minutes, goals = EXCLUDED.goals,
                     shots = EXCLUDED.shots, shots_on_target = EXCLUDED.shots_on_target""",
                (match_id, pid, tid, minutes, goals.get("total") or 0,
                 goals.get("assists") or 0, shots.get("total"), shots.get("on"),
                 passes.get("key"), goals.get("saves"), goals.get("conceded")))


def backfill_primary(league_code: str, season_start_year: int):
    """
    Full primary-source backfill for leagues with no Understat/FBref
    coverage (MLS). API-Football supplies schedule, results, AND stats
    in one pass — creates match rows directly rather than matching
    onto pre-existing ones. No xG (not available on this tier); the
    Dixon-Coles match model doesn't need it, only goals.
    """
    session = _session()
    league_id_api = resolve_league_id(session, league_code)
    league_name, _ = LEAGUE_SEARCH[league_code]
    season_label = f"{season_start_year}"

    conn = psycopg2.connect(DSN)
    fixtures = _get(session, "fixtures",
                    {"league": league_id_api, "season": season_start_year})
    log.info("%d total fixtures (all statuses) from API-Football", len(fixtures))

    created, updated_stats = 0, 0
    with conn.cursor() as cur:
        season_id = upsert_league_season(cur, league_code, league_name, season_label)
        conn.commit()

        for fx in fixtures:
            fixture_id = fx["fixture"]["id"]
            kickoff = fx["fixture"]["date"]
            short_status = fx["fixture"]["status"]["short"]
            home_api_id = fx["teams"]["home"]["id"]
            away_api_id = fx["teams"]["away"]["id"]
            hg = fx["goals"]["home"]
            ag = fx["goals"]["away"]

            home_id = resolve_or_create_team_id(cur, home_api_id, fx["teams"]["home"]["name"])
            away_id = resolve_or_create_team_id(cur, away_api_id, fx["teams"]["away"]["name"])

            status = "final" if short_status == "FT" else (
                "scheduled" if short_status in ("NS", "TBD") else short_status.lower())

            cur.execute(
                """INSERT INTO futbol.matches
                     (season_id, home_team_id, away_team_id, kickoff_utc,
                      home_goals, away_goals, status, external_ref)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (season_id, home_team_id, away_team_id, kickoff_utc)
                   DO UPDATE SET home_goals = EXCLUDED.home_goals,
                                 away_goals = EXCLUDED.away_goals,
                                 status     = EXCLUDED.status
                   RETURNING match_id""",
                (season_id, home_id, away_id, kickoff, hg, ag, status,
                 f"api-football:{fixture_id}"))
            match_id = cur.fetchone()[0]
            created += 1

            if status == "final":
                for tid, is_home in ((home_id, True), (away_id, False)):
                    cur.execute(
                        """INSERT INTO futbol.team_match_stats (match_id, team_id, is_home)
                           VALUES (%s,%s,%s)
                           ON CONFLICT (match_id, team_id) DO NOTHING""",
                        (match_id, tid, is_home))

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
                updated_stats += 1

                load_fixture_players(session, cur, match_id, fixture_id,
                                     home_id, away_id, home_api_id)

            if created % 20 == 0:
                conn.commit()
                log.info("progress: %d/%d fixtures processed", created, len(fixtures))

        conn.commit()
    conn.close()
    log.info("done: %d matches created/updated, %d had stats filled",
             created, updated_stats)


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
    ap.add_argument("--primary", action="store_true",
                    help="Use API-Football as the sole source for future/unplayed seasons")
    args = ap.parse_args()
    if args.league == "MLS" or args.primary:
        backfill_primary(args.league, args.season)
    else:
        backfill(args.league, args.season)


if __name__ == "__main__":
    main()
