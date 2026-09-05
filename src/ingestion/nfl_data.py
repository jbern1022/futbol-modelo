"""
NFL ingestion via nfl_data_py (wraps nflverse's free, open, CC-BY-licensed
data -- no API key, no rate limit, unlike API-Football). Pulls the season
schedule (scores once played, real historical closing lines always) and
upserts into the shared matches table -- same shape soccer already uses,
no NFL-specific matches columns needed.

    python -m ingestion.nfl_data backfill --season 2026

nfl_data_py pins pandas<2.0/numpy<2.0, which conflicts with this
project's pandas==3.0.3/numpy==2.5.1 -- installed separately with
--no-deps (see requirements-nfl.txt and the Dockerfile). Verified
locally that nfl_data_py's actual code works fine against the modern
pandas/numpy already installed; its pin is just overly conservative.
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import nfl_data_py as nfl
import pandas as pd
import psycopg2

log = logging.getLogger("nfl_data")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# nflverse's own documented convention: gametime is a local wall-clock
# time in US/Eastern regardless of the actual stadium's timezone.
GAME_TZ = ZoneInfo("America/New_York")


def _kickoff_utc(gameday: str, gametime: str | None) -> datetime:
    time_str = gametime if isinstance(gametime, str) and gametime else "13:00"
    naive = datetime.strptime(f"{gameday} {time_str}", "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=GAME_TZ)


def upsert_nfl_season(cur, season_start_year: int) -> int:
    cur.execute(
        """INSERT INTO futbol.leagues (code, name, sport) VALUES ('NFL', 'National Football League', 'football')
           ON CONFLICT (code) DO NOTHING""")
    cur.execute("SELECT league_id FROM futbol.leagues WHERE code = 'NFL'")
    league_id = cur.fetchone()[0]
    label = str(season_start_year)
    cur.execute(
        """INSERT INTO futbol.seasons (league_id, label) VALUES (%s, %s)
           ON CONFLICT (league_id, label) DO UPDATE SET label = EXCLUDED.label
           RETURNING season_id""", (league_id, label))
    return cur.fetchone()[0]


def _team_id(cur, abbr: str) -> int:
    cur.execute("SELECT team_id FROM futbol.teams WHERE nfl_abbr = %s", (abbr,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"no team seeded for nfl_abbr={abbr!r} -- run migration 0013 first")
    return row[0]


def backfill(season_start_year: int) -> int:
    """
    Pulls the full season schedule (all weeks, played and unplayed) and
    upserts every game into matches, keyed by external_ref so reruns
    (score updates, kickoff-time corrections) update in place rather
    than duplicating -- same pattern as backfill_primary() in
    api_football.py.
    """
    df = nfl.import_schedules([season_start_year])
    log.info("%d games for %d season from nflverse", len(df), season_start_year)

    conn = psycopg2.connect(DSN)
    created = 0
    with conn.cursor() as cur:
        season_id = upsert_nfl_season(cur, season_start_year)
        conn.commit()

        for _, row in df.iterrows():
            ext_ref = f"nflverse:{row['game_id']}"
            home_id = _team_id(cur, row["home_team"])
            away_id = _team_id(cur, row["away_team"])
            kickoff = _kickoff_utc(row["gameday"], row.get("gametime"))

            home_score = None if pd.isna(row["home_score"]) else int(row["home_score"])
            away_score = None if pd.isna(row["away_score"]) else int(row["away_score"])
            status = "final" if home_score is not None else "scheduled"
            went_to_ot = bool(row.get("overtime")) if not pd.isna(row.get("overtime")) else False

            cur.execute("SELECT match_id FROM futbol.matches WHERE external_ref = %s", (ext_ref,))
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """UPDATE futbol.matches
                       SET kickoff_utc = %s, home_score = %s, away_score = %s,
                           status = %s, went_to_ot = %s
                       WHERE match_id = %s""",
                    (kickoff, home_score, away_score, status, went_to_ot, existing[0]))
            else:
                cur.execute(
                    """INSERT INTO futbol.matches
                         (season_id, home_team_id, away_team_id, kickoff_utc,
                          home_score, away_score, status, went_to_ot, external_ref)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (season_id, home_team_id, away_team_id, kickoff_utc)
                       DO UPDATE SET home_score = EXCLUDED.home_score,
                                     away_score = EXCLUDED.away_score,
                                     status     = EXCLUDED.status,
                                     went_to_ot = EXCLUDED.went_to_ot,
                                     external_ref = COALESCE(futbol.matches.external_ref, EXCLUDED.external_ref)""",
                    (season_id, home_id, away_id, kickoff, home_score, away_score,
                     status, went_to_ot, ext_ref))
            created += 1
            if created % 50 == 0:
                conn.commit()
                log.info("progress: %d/%d games processed", created, len(df))

        conn.commit()
    conn.close()
    log.info("done: %d games created/updated", created)
    return created


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["backfill"])
    ap.add_argument("--season", type=int, required=True,
                    help="Season START year, e.g. 2026 for the 2026 NFL season")
    args = ap.parse_args()
    from ops.pipeline_run import track_run

    with track_run(f"nfl_backfill:{args.season}") as set_rows_written:
        n = backfill(args.season)
        set_rows_written(n)


if __name__ == "__main__":
    main()
