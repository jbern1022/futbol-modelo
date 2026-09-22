"""
NFL ingestion via nfl_data_py (wraps nflverse's free, open, CC-BY-licensed
data -- no API key, no rate limit, unlike API-Football). Pulls the season
schedule (scores once played, real historical closing lines always) and
upserts into the shared matches table -- same shape soccer already uses,
no NFL-specific matches columns needed.

    python -m ingestion.nfl_data backfill --season 2026
    python -m ingestion.nfl_data backfill-players --season 2026
    (backfill-players: QB/RB/WR/TE weekly box scores + snap share,
    feeding the PLAYER_PASS_YARDS/PLAYER_RUSH_YARDS/PLAYER_RECEIVING_YARDS/
    PLAYER_RECEPTIONS/PLAYER_ANYTIME_TD markets -- run backfill() for the
    same season first, rows are matched onto existing match external_refs
    via a schedule-derived (week, team) -> game_id lookup)

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


def _resolve_or_create_player(cur, nfl_player_id: str, player_name: str) -> int:
    cur.execute("SELECT player_id FROM futbol.players WHERE nfl_player_id = %s", (nfl_player_id,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO futbol.players (full_name, nfl_player_id) VALUES (%s, %s)
           RETURNING player_id""", (player_name, nfl_player_id))
    return cur.fetchone()[0]


def _game_id_by_team_week(season_start_year: int) -> dict[tuple[int, str], str]:
    """weekly stats and snap counts carry (season, week, team), not
    game_id -- this bridges them to matches' external_ref, which IS
    keyed by game_id, via the schedule (the one dataset with both)."""
    sched = nfl.import_schedules([season_start_year])
    lookup: dict[tuple[int, str], str] = {}
    for _, row in sched.iterrows():
        lookup[(int(row["week"]), row["home_team"])] = row["game_id"]
        lookup[(int(row["week"]), row["away_team"])] = row["game_id"]
    return lookup


STAT_COLUMNS = ["passing_yards", "passing_tds", "rushing_yards", "rushing_tds",
                "receptions", "receiving_yards", "receiving_tds", "targets"]

# QB/RB/WR/TE -- expanded from the original QB/RB-only scope (passing
# and rushing yards) to also feed receptions/receiving-yards/anytime-TD
# props. Kickers/defense excluded -- out of scope, no props planned.
INGESTED_POSITIONS = ["QB", "RB", "WR", "TE"]


def _weekly_stats_url(season_start_year: int) -> str:
    return (f"https://github.com/nflverse/nflverse-data/releases/download/"
            f"stats_player/stats_player_week_{season_start_year}.parquet")


def backfill_player_stats(season_start_year: int) -> int:
    """
    QB/RB/WR/TE weekly box scores -- passing/rushing/receiving yards and
    TDs, receptions, targets -- feeding this project's NFL player props
    (see nfl_player_props.py). Also pulls snap share (import_snap_counts)
    -- the real per-week usage signal candidate_lines()'s depth-chart
    gate needs, since a rolling yardage average alone can't see a
    committee role change until several games after it happens.

    Real incident, 2026-09-14: nfl_data_py==0.3.3's import_weekly_data()
    points to nflverse-data's "player_stats" GitHub release, which
    nflverse itself renamed to "stats_player" in July 2025 -- confirmed
    directly (the old release's most recent asset is season 2024; the
    new one has 2025 and the current season, 2026). nfl_data_py is
    unmaintained (0.3.3 is both the pinned AND the latest version on
    PyPI, checked directly) and will never be fixed upstream, so this
    reads the new release's parquet file directly with pandas rather
    than going through the broken library function. Silently zero
    output every night since whenever this project's "current season"
    rolled past 2024 -- the nightly cron never errored, it just had
    nothing to insert, since the season it asked for genuinely returned
    a 404 that only ever surfaced as "0 rows stored" in a log line
    nobody was watching for a null result specifically.

    snap_counts keys players by Pro-Football-Reference id, not
    nflverse's own gsis_id that weekly_data/depth_charts use -- import_ids()
    is the crosswalk (verified: Josh Allen's gsis_id and pfr_id map to
    the exact same player via this table).
    """
    game_ids = _game_id_by_team_week(season_start_year)

    weekly = pd.read_parquet(_weekly_stats_url(season_start_year))
    weekly = weekly[(weekly["season_type"] == "REG") &
                    (weekly["position"].isin(INGESTED_POSITIONS))]
    log.info("%d %s weekly rows for %d season from nflverse (stats_player release)",
            len(weekly), "/".join(INGESTED_POSITIONS), season_start_year)

    snaps = nfl.import_snap_counts([season_start_year])
    ids = nfl.import_ids()
    pfr_to_gsis = dict(zip(ids["pfr_id"], ids["gsis_id"]))
    snap_pct_by_player_week: dict[tuple[str, int], float] = {}
    for _, row in snaps.iterrows():
        gsis = pfr_to_gsis.get(row["pfr_player_id"])
        if gsis:
            snap_pct_by_player_week[(gsis, int(row["week"]))] = row["offense_pct"]

    conn = psycopg2.connect(DSN)
    stored, skipped_no_match = 0, 0
    with conn.cursor() as cur:
        for _, row in weekly.iterrows():
            # "team", not the old release's "recent_team" -- the new
            # stats_player schema renamed this column too.
            game_id = game_ids.get((int(row["week"]), row["team"]))
            ext_ref = f"nflverse:{game_id}" if game_id else None
            match_id = None
            if ext_ref:
                cur.execute("SELECT match_id FROM futbol.matches WHERE external_ref = %s", (ext_ref,))
                match = cur.fetchone()
                match_id = match[0] if match else None
            if match_id is None:
                skipped_no_match += 1
                continue

            team_id = _team_id(cur, row["team"])
            player_id = _resolve_or_create_player(cur, row["player_id"], row["player_display_name"])
            snap_pct = snap_pct_by_player_week.get((row["player_id"], int(row["week"])))
            stat_values = [None if pd.isna(row[c]) else int(row[c]) for c in STAT_COLUMNS]

            cur.execute(
                f"""INSERT INTO futbol.player_match_stats_nfl
                     (match_id, player_id, team_id, position, snap_pct,
                      {', '.join(STAT_COLUMNS)})
                   VALUES (%s,%s,%s,%s,%s,{','.join(['%s'] * len(STAT_COLUMNS))})
                   ON CONFLICT (match_id, player_id)
                   DO UPDATE SET position = EXCLUDED.position,
                                 snap_pct = EXCLUDED.snap_pct,
                                 {', '.join(f'{c} = EXCLUDED.{c}' for c in STAT_COLUMNS)}""",
                (match_id, player_id, team_id, row["position"], snap_pct, *stat_values))
            stored += 1
            if stored % 200 == 0:
                conn.commit()
                log.info("progress: %d/%d rows processed", stored, len(weekly))

        conn.commit()
    conn.close()
    log.info("done: %d rows stored, %d skipped (no matching match)", stored, skipped_no_match)
    return stored


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["backfill", "backfill-players"])
    ap.add_argument("--season", type=int, required=True,
                    help="Season START year, e.g. 2026 for the 2026 NFL season")
    args = ap.parse_args()
    from ops.json_logging import configure_json_logging
    from ops.pipeline_run import track_run

    job_name = (f"nfl_backfill_players:{args.season}" if args.mode == "backfill-players"
                else f"nfl_backfill:{args.season}")
    configure_json_logging(job_name)

    if args.mode == "backfill-players":
        with track_run(f"nfl_backfill_players:{args.season}") as set_rows_written:
            n = backfill_player_stats(args.season)
            set_rows_written(n)
        return

    with track_run(f"nfl_backfill:{args.season}") as set_rows_written:
        n = backfill(args.season)
        set_rows_written(n)


if __name__ == "__main__":
    main()
