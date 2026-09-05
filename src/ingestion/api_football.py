"""
API-Football integration — fills the gap FBref left blocked (corners,
cards, saves, shots-on-target, possession). Matches onto the *existing*
matches table (built from Understat) via team name + date, rather than
creating a second, parallel set of match rows.

    python -m ingestion.api_football backfill --league EPL --season 2025
    (API-Football uses the year the season STARTS, e.g. 2025 = 2025-26)

    python -m ingestion.api_football odds --league MLS --days-ahead 7
    (odds mode: MLS only for now -- the only league whose matches carry
    an api-football:<fixture_id> external_ref to look odds up by; see
    _api_football_fixture_id())
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
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

# /tmp, not Path.home(): the container's home dir (/app, per the
# Dockerfile's `useradd -d /app`) is root-owned -- only the specific
# subdirectories COPY --chown'd to appuser are writable, so writing
# here as the non-root appuser always failed. /tmp is writable
# regardless of the running user in virtually every base image. Each
# CronJob run is a fresh pod anyway, so this only ever helped within
# one script execution's repeated calls, never across separate runs.
CACHE_FILE = Path("/tmp/.api_football_cache.json")


def _session() -> requests.Session:
    if not API_KEY:
        raise SystemExit("API_FOOTBALL_KEY not set — export it first.")
    s = requests.Session()
    s.headers.update({"x-apisports-key": API_KEY})
    return s


def _get(session: requests.Session, endpoint: str, params: dict, attempts: int = 3) -> list:
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            resp = session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.exceptions.RequestException(
                    f"transient {resp.status_code} on {endpoint}")
            resp.raise_for_status()
            data = resp.json()
            if data.get("errors"):
                raise RuntimeError(f"API-Football error on {endpoint}: {data['errors']}")
            time.sleep(0.3)
            return data.get("response", [])
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            last_err = e
            if attempt == attempts:
                break
            wait = 5 * attempt
            log.info("request to %s failed (attempt %d/%d: %s), retrying in %ds...",
                     endpoint, attempt, attempts, e, wait)
            time.sleep(wait)
    raise RuntimeError(
        f"API-Football request to {endpoint} failed after {attempts} attempts"
    ) from last_err


def normalize_match_winner_odds(response: list[dict]) -> list[dict]:
    """Flatten API-Football match-winner odds into database-ready records."""
    records = []
    for fixture in response:
        fixture_id = fixture.get("fixture", {}).get("id")
        for bookmaker in fixture.get("bookmakers", []):
            for bet in bookmaker.get("bets", []):
                if bet.get("id") != 1:
                    continue
                for value in bet.get("values", []):
                    try:
                        decimal_odds = float(value["odd"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if fixture_id is None or decimal_odds <= 1:
                        continue
                    records.append({
                        "fixture_id": fixture_id,
                        "bookmaker_id": bookmaker.get("id"),
                        "bookmaker_name": bookmaker.get("name"),
                        "market": "1X2",
                        "selection": value.get("value"),
                        "decimal_odds": decimal_odds,
                    })
    return records


def remove_overround(records: list[dict]) -> list[dict]:
    """Add raw and no-vig implied probabilities to one bookmaker market."""
    probabilities = []
    for record in records:
        probability = 1 / record["decimal_odds"]
        probabilities.append(probability)
        record["implied_probability"] = probability

    total_probability = sum(probabilities)
    if total_probability <= 0:
        return records
    for record in records:
        record["no_vig_probability"] = record["implied_probability"] / total_probability
    return records


_API_FOOTBALL_REF_PATTERN = re.compile(r"^api-football:(\d+)$")


def _api_football_fixture_id(external_ref: str | None) -> int | None:
    """
    Only matches created by backfill_primary() (MLS today) carry this
    external_ref format -- EPL/SERIE_A/LA_LIGA matches come from
    Understat/FBref via loader.py and have no stored mapping to an
    API-Football fixture id at all, so odds can't be fetched for them
    yet (same MLS-only phasing already used for player props -- the
    only league with player_match_stats populated). Resolving that
    for the other leagues is real, separate work: it would need its
    own team+date fixture lookup against API-Football, similar to
    backfill()'s stats lookup but for a league that never gets a
    match_id from this module in the first place.
    """
    if not external_ref:
        return None
    m = _API_FOOTBALL_REF_PATTERN.match(external_ref)
    return int(m.group(1)) if m else None


def fetch_and_store_odds(league_code: str, days_ahead: int = 7) -> int:
    """
    Storage half of the real bookmaker odds comparison feature (Track
    Record UI display is separate, deferred work). Fetches
    match-winner (1X2) odds for already-known, still-scheduled fixtures
    in the next `days_ahead` days, strips each bookmaker's own
    overround, and upserts into match_odds (latest snapshot per
    match/bookmaker/selection, not a full time series -- see
    sql/migrations/0010_match_odds.sql).

    One real API call per matching fixture -- keep days_ahead modest
    on a rate-limited API-Football tier; this does not batch across
    fixtures the way the /fixtures listing endpoint does.
    """
    session = _session()
    conn = psycopg2.connect(DSN)
    stored = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT m.match_id, m.external_ref, th.name, ta.name
                   FROM futbol.matches m
                   JOIN futbol.teams th ON th.team_id = m.home_team_id
                   JOIN futbol.teams ta ON ta.team_id = m.away_team_id
                   JOIN futbol.seasons s ON s.season_id = m.season_id
                   JOIN futbol.leagues l ON l.league_id = s.league_id
                   WHERE l.code = %s AND m.status = 'scheduled'
                     AND m.kickoff_utc BETWEEN now() AND now() + (%s || ' days')::interval""",
                (league_code, days_ahead))
            fixtures = cur.fetchall()

        log.info("%d scheduled %s fixture(s) in the next %d day(s)",
                 len(fixtures), league_code, days_ahead)

        for match_id, external_ref, home, away in fixtures:
            fixture_id = _api_football_fixture_id(external_ref)
            if fixture_id is None:
                log.info("no API-Football fixture id for %s vs %s -- skipping odds", home, away)
                continue

            response = _get(session, "odds", {"fixture": fixture_id})
            records = normalize_match_winner_odds(response)
            if not records:
                continue

            # remove_overround normalizes probabilities within one
            # bookmaker's own market -- grouping by bookmaker first so a
            # multi-bookmaker response doesn't get treated as one market.
            by_bookmaker: dict[int | None, list[dict]] = {}
            for r in records:
                by_bookmaker.setdefault(r["bookmaker_id"], []).append(r)

            with conn.cursor() as cur:
                for bookmaker_records in by_bookmaker.values():
                    for r in remove_overround(bookmaker_records):
                        cur.execute(
                            """INSERT INTO futbol.match_odds
                                 (match_id, bookmaker_id, bookmaker_name, market,
                                  selection, decimal_odds, implied_probability, no_vig_probability)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT (match_id, bookmaker_id, market, selection)
                               DO UPDATE SET decimal_odds = EXCLUDED.decimal_odds,
                                             implied_probability = EXCLUDED.implied_probability,
                                             no_vig_probability = EXCLUDED.no_vig_probability,
                                             fetched_at = now()""",
                            (match_id, r["bookmaker_id"], r["bookmaker_name"], r["market"],
                             r["selection"], r["decimal_odds"], r["implied_probability"],
                             r["no_vig_probability"]))
                        stored += 1
            conn.commit()
    finally:
        conn.close()
    log.info("done: %d odds record(s) stored/updated", stored)
    return stored


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


def find_match_id(cur, home_team_id: int, away_team_id: int, date: str,
                  league_code: str | None = None) -> int | None:
    """+/-1 day tolerance: sources occasionally disagree on which
    calendar day a match falls on across a UTC boundary. Scoped to the
    league being loaded when known -- the same two teams can meet twice
    in a short window across league + cup competitions."""
    if league_code is not None:
        cur.execute(
            """SELECT m.match_id FROM futbol.matches m
               JOIN futbol.seasons s ON s.season_id = m.season_id
               JOIN futbol.leagues l ON l.league_id = s.league_id
               WHERE m.home_team_id = %s AND m.away_team_id = %s
                 AND DATE(m.kickoff_utc) BETWEEN %s::date - 1 AND %s::date + 1
                 AND l.code = %s
               ORDER BY ABS(DATE(m.kickoff_utc) - %s::date) LIMIT 1""",
            (home_team_id, away_team_id, date, date, league_code, date))
    else:
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


# Leagues spanning two calendar years have used the hyphenated "YYYY-YY"
# label (matching loader.py's _season_label) for every prior season in
# the DB -- MLS is a single-calendar-year competition where the bare
# year is correct. A previous version of season_label_for() used bare
# year unconditionally, which created a real mismatch: a second,
# duplicate season row the moment loader.py or a human ever looked up
# "the current EPL season" by its established hyphenated format.
CROSS_YEAR_LEAGUES = ("EPL", "SERIE_A", "LA_LIGA")


def season_label_for(league_code: str, season_start_year: int) -> str:
    if league_code in CROSS_YEAR_LEAGUES:
        return f"{season_start_year}-{str(season_start_year + 1)[-2:]}"
    return f"{season_start_year}"


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
    season_label = season_label_for(league_code, season_start_year)

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
            ext_ref = f"api-football:{fixture_id}"

            # A kickoff-time correction between runs (broadcast
            # rescheduling -- real and common) changes the old conflict
            # key (season, home, away, kickoff_utc), so an ON CONFLICT
            # on that key alone inserted a duplicate row instead of
            # updating the existing one. Found live: 9 real fixtures each
            # ended up as two match rows this way. Look up by the stable
            # external_ref first; only fall back to the natural key for
            # a genuinely new fixture (which also covers the case where
            # another source already created this real match under a
            # different external_ref format).
            cur.execute("SELECT match_id FROM futbol.matches WHERE external_ref = %s", (ext_ref,))
            existing = cur.fetchone()
            if existing:
                match_id = existing[0]
                cur.execute(
                    """UPDATE futbol.matches
                       SET kickoff_utc = %s, home_score = %s, away_score = %s, status = %s
                       WHERE match_id = %s""",
                    (kickoff, hg, ag, status, match_id))
            else:
                cur.execute(
                    """INSERT INTO futbol.matches
                         (season_id, home_team_id, away_team_id, kickoff_utc,
                          home_score, away_score, status, external_ref)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (season_id, home_team_id, away_team_id, kickoff_utc)
                       DO UPDATE SET home_score = EXCLUDED.home_score,
                                     away_score = EXCLUDED.away_score,
                                     status     = EXCLUDED.status,
                                     external_ref = COALESCE(futbol.matches.external_ref, EXCLUDED.external_ref)
                       RETURNING match_id""",
                    (season_id, home_id, away_id, kickoff, hg, ag, status, ext_ref))
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
    return created


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

            match_id = find_match_id(cur, home_id, away_id, date, league_code)
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
    return updated


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["backfill", "odds"])
    ap.add_argument("--league", required=True, choices=list(LEAGUE_SEARCH))
    ap.add_argument("--season", type=int,
                    help="Season START year, e.g. 2025 for the 2025-26 season "
                         "(required for backfill, unused for odds)")
    ap.add_argument("--primary", action="store_true",
                    help="Use API-Football as the sole source for future/unplayed seasons")
    ap.add_argument("--days-ahead", type=int, default=7,
                    help="odds mode only: fetch odds for fixtures within this many days (default 7)")
    args = ap.parse_args()
    from ops.pipeline_run import track_run

    if args.mode == "odds":
        with track_run(f"odds:{args.league}") as set_rows_written:
            n = fetch_and_store_odds(args.league, args.days_ahead)
            set_rows_written(n)
        return

    if args.season is None:
        raise SystemExit("--season is required for backfill mode")
    job_name = f"nightly_refresh:{args.league}"
    with track_run(job_name) as set_rows_written:
        if args.league == "MLS" or args.primary:
            n = backfill_primary(args.league, args.season)
        else:
            n = backfill(args.league, args.season)
        set_rows_written(n)


if __name__ == "__main__":
    main()
