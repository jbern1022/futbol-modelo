"""
NBA ingestion via nba_api (wraps stats.nba.com -- free, no API key,
same phasing as the NFL/nflverse path: no separate odds/paid source
needed for the TOTAL_POINTS market, which self-generates its own line
from the model rather than predicting against a real bookmaker line --
see nba_power_ratings.py). Regular-season games only (gameId prefix
'002') -- preseason is bench-heavy/unrepresentative, playoffs are a
distinct scope not attempted yet.

ScheduleLeagueV2 alone covers both schedule (future, unplayed) and
results (final, with real scores) in one call -- no separate
completed-games endpoint needed, unlike NFL where schedules and
results were also one call but via a different package (nfl_data_py).

    python -m ingestion.nba_data backfill --season 2026-27
"""
from __future__ import annotations

import argparse
import logging
import os

import psycopg2
from nba_api.stats.endpoints import scheduleleaguev2

log = logging.getLogger("nba_data")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

REGULAR_SEASON_PREFIX = "002"


def upsert_nba_season(cur, season_label: str) -> int:
    cur.execute(
        """INSERT INTO futbol.leagues (code, name, sport)
           VALUES ('NBA', 'National Basketball Association', 'basketball')
           ON CONFLICT (code) DO NOTHING""")
    cur.execute("SELECT league_id FROM futbol.leagues WHERE code = 'NBA'")
    league_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO futbol.seasons (league_id, label) VALUES (%s, %s)
           ON CONFLICT (league_id, label) DO UPDATE SET label = EXCLUDED.label
           RETURNING season_id""", (league_id, season_label))
    return cur.fetchone()[0]


def _team_id(cur, nba_team_id: int) -> int:
    cur.execute("SELECT team_id FROM futbol.teams WHERE nba_team_id = %s", (nba_team_id,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"no team seeded for nba_team_id={nba_team_id!r} -- run migration 0014 first")
    return row[0]


def backfill(season: str) -> int:
    """season: nba_api's own format, e.g. '2026-27'."""
    sched = scheduleleaguev2.ScheduleLeagueV2(season=season)
    df = sched.get_data_frames()[0]
    df = df[df["gameId"].str.startswith(REGULAR_SEASON_PREFIX)]
    log.info("%d regular-season games for %s from nba_api", len(df), season)

    conn = psycopg2.connect(DSN)
    created, skipped_tbd = 0, 0
    with conn.cursor() as cur:
        season_id = upsert_nba_season(cur, season)
        conn.commit()

        for _, row in df.iterrows():
            # NBA Cup knockout games (quarterfinal/semifinal) are scheduled
            # by date before their participants are determined by group
            # play -- team id 0 on both sides. Skip; re-running backfill()
            # after group play resolves them will pick these up for real.
            if row["homeTeam_teamId"] == 0 or row["awayTeam_teamId"] == 0:
                skipped_tbd += 1
                continue

            ext_ref = f"nba:{row['gameId']}"
            home_id = _team_id(cur, row["homeTeam_teamId"])
            away_id = _team_id(cur, row["awayTeam_teamId"])
            kickoff = row["gameDateTimeUTC"]

            is_final = int(row["gameStatus"]) == 3
            home_score = int(row["homeTeam_score"]) if is_final else None
            away_score = int(row["awayTeam_score"]) if is_final else None
            status = "final" if is_final else "scheduled"

            cur.execute("SELECT match_id FROM futbol.matches WHERE external_ref = %s", (ext_ref,))
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """UPDATE futbol.matches
                       SET kickoff_utc = %s, home_score = %s, away_score = %s, status = %s
                       WHERE match_id = %s""",
                    (kickoff, home_score, away_score, status, existing[0]))
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
                                     external_ref = COALESCE(futbol.matches.external_ref, EXCLUDED.external_ref)""",
                    (season_id, home_id, away_id, kickoff, home_score, away_score,
                     status, ext_ref))
            created += 1
            if created % 100 == 0:
                conn.commit()
                log.info("progress: %d/%d games processed", created, len(df))

        conn.commit()
    conn.close()
    log.info("done: %d games created/updated, %d skipped (TBD participants)",
             created, skipped_tbd)
    return created


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["backfill"])
    ap.add_argument("--season", required=True, help="e.g. 2026-27")
    args = ap.parse_args()
    from ops.pipeline_run import track_run

    with track_run(f"nba_backfill:{args.season}") as set_rows_written:
        n = backfill(args.season)
        set_rows_written(n)


if __name__ == "__main__":
    main()
