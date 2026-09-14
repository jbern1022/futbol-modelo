"""
One-time (per league) backfill of team_venues: fetches each team's home
venue city from API-Football's /teams endpoint (already the ingestion
source this project uses for everything else), geocodes the city via
Open-Meteo's free geocoding API (no key required), and stores
city-level coordinates -- precise enough for weather, which doesn't
meaningfully vary at football-stadium scale within a city.

    python scripts/backfill_team_venues.py --league MLS --season 2025

Pilot scope: MLS only for now (see scripts/train_weather_feature.py's
own scope note) -- the pattern generalizes to any league API-Football
covers, just not run for the others yet.
"""
from __future__ import annotations

import argparse
import os
import time

import psycopg2
import requests

API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
OPEN_METEO_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

LEAGUE_API_FOOTBALL_ID = {"MLS": 253, "EPL": 39, "SERIE_A": 135, "LA_LIGA": 140}


API_FOOTBALL_COUNTRY_TO_ISO = {"USA": "US", "Canada": "CA"}


def geocode_city(session: requests.Session, city: str, country: str) -> tuple[float, float] | None:
    """API-Football's venue.city is "City, State" (e.g. "Seattle,
    Washington") for US venues. City names collide a lot even within
    one country (5 different "Chester"s across US states alone,
    checked directly) -- Open-Meteo's own `country` query param does
    NOT reliably filter/prioritize by itself (verified: "Chester" with
    country=US still returned Chester, England first). Fetches several
    candidates and filters/matches client-side instead of trusting the
    first result."""
    parts = [p.strip() for p in city.split(",")]
    city_name = parts[0]
    state_name = parts[1] if len(parts) > 1 else None
    iso = API_FOOTBALL_COUNTRY_TO_ISO.get(country)

    resp = session.get(
        OPEN_METEO_GEOCODE, params={"name": city_name, "count": 10}, timeout=15)
    resp.raise_for_status()
    results = resp.json().get("results") or []
    if not results:
        return None

    if iso:
        results = [r for r in results if r.get("country_code") == iso] or results

    if state_name and len(results) > 1:
        state_matches = [r for r in results
                          if state_name.lower() in (r.get("admin1") or "").lower()]
        if state_matches:
            results = state_matches

    best = results[0]
    return best["latitude"], best["longitude"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=list(LEAGUE_API_FOOTBALL_ID))
    ap.add_argument("--season", type=int, required=True)
    args = ap.parse_args()

    if not API_FOOTBALL_KEY:
        raise SystemExit("API_FOOTBALL_KEY must be set")

    session = requests.Session()
    session.headers.update({"x-apisports-key": API_FOOTBALL_KEY})

    resp = session.get(
        f"{API_FOOTBALL_BASE}/teams",
        params={"league": LEAGUE_API_FOOTBALL_ID[args.league], "season": args.season},
        timeout=15)
    resp.raise_for_status()
    teams = resp.json()["response"]
    print(f"{len(teams)} {args.league} teams from API-Football")

    conn = psycopg2.connect(DSN)
    stored, skipped = 0, 0
    with conn.cursor() as cur:
        for row in teams:
            team = row["team"]
            venue = row["venue"]
            api_football_id = team["id"]
            city = venue.get("city")
            if not city:
                print(f"  SKIP {team['name']}: no venue city from API-Football")
                skipped += 1
                continue

            coords = geocode_city(session, city, team.get("country", ""))
            if coords is None:
                print(f"  SKIP {team['name']}: Open-Meteo found no match for '{city}'")
                skipped += 1
                continue
            lat, lon = coords

            cur.execute(
                """SELECT team_id FROM futbol.teams WHERE api_football_id = %s""",
                (api_football_id,))
            found = cur.fetchone()
            if found is None:
                print(f"  SKIP {team['name']}: no matching team_id for "
                      f"api_football_id={api_football_id}")
                skipped += 1
                continue
            team_id = found[0]

            cur.execute(
                """INSERT INTO futbol.team_venues
                     (team_id, venue_name, city, country, latitude, longitude)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (team_id) DO UPDATE
                     SET venue_name = EXCLUDED.venue_name, city = EXCLUDED.city,
                         country = EXCLUDED.country, latitude = EXCLUDED.latitude,
                         longitude = EXCLUDED.longitude, fetched_at = now()""",
                (team_id, venue.get("name"), city, venue.get("country") or team.get("country"),
                 lat, lon))
            print(f"  {team['name']:<25s} {city:<25s} -> ({lat:.4f}, {lon:.4f})")
            stored += 1
            time.sleep(0.2)  # be polite to the free geocoding API
    conn.commit()
    conn.close()
    print(f"\nStored {stored}, skipped {skipped}")


if __name__ == "__main__":
    main()
