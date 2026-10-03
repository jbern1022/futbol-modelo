"""
Understat shots + team xG onto EXISTING match rows (ADR-015).

loader.py's load_understat() upserts matches itself, which is right when
Understat is a league's primary source (EPL/SERIE_A history) but wrong
when the matches already exist from API-Football (La Liga 2021-25): an
exact kickoff match keeps the API-Football row and silently drops the
shots, and any kickoff difference creates a duplicate match (the
2025-26 La Liga load made 4). This script never creates a match:

  1. schedule: resolve both teams (an unknown Understat name aborts the
     run before anything is written), find the existing final match in
     the same league by teams + date (+-2 days), record its
     understat_game_id. Unmatched games are reported, not inserted.
  2. team xG: fill team_match_stats.xg only where it's NULL.
  3. shots: attach by understat_game_id, same insert as loader.py.

    python scripts/backfill_understat_shots.py --league LA_LIGA --seasons 2122 2223 2324 2425 --dry-run
    python scripts/backfill_understat_shots.py --league LA_LIGA --seasons 2122 2223 2324 2425

Understat's terms of service are still unconfirmed (docs/DATA_LICENSING.md);
this extends the project's existing historical use of it to one more league.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2

from ingestion import entities
from ingestion.loader import LEAGUES, _clean, _int, _num, upsert_team

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

FIND_MATCH_SQL = """
SELECT m.match_id, m.understat_game_id
FROM futbol.matches m
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
WHERE l.code = %s AND th.name = %s AND ta.name = %s AND m.status = 'final'
  AND m.kickoff_utc::date BETWEEN %s::date - 2 AND %s::date + 2
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["EPL", "SERIE_A", "LA_LIGA"])
    ap.add_argument("--seasons", nargs="+", required=True, help="soccerdata season codes, e.g. 2122")
    ap.add_argument("--dry-run", action="store_true",
                    help="schedule mapping only: no match-page fetches, no writes")
    args = ap.parse_args()

    import soccerdata as sd
    lg = LEAGUES[args.league]
    us = sd.Understat(leagues=[lg["soccerdata"]], seasons=args.seasons)
    sched = us.read_schedule().reset_index()
    log.info("Understat schedule: %d games", len(sched))

    # 1. Resolve every team first -- an unmapped name stops the run cold.
    unknown = set()
    for name in set(sched.home_team) | set(sched.away_team):
        try:
            entities.resolve_team("understat", name)
        except entities.UnknownTeamError:
            unknown.add(name)
    if unknown:
        raise SystemExit(f"unmapped Understat team names (add to TEAM_SEED, don't guess): {sorted(unknown)}")

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    links, unmatched, ambiguous, conflicts = [], [], [], []
    for r in sched.itertuples():
        game_id = _clean(getattr(r, "game_id", None))
        if game_id is None or not getattr(r, "is_result", True):
            continue
        home = entities.resolve_team("understat", r.home_team)
        away = entities.resolve_team("understat", r.away_team)
        cur.execute(FIND_MATCH_SQL, (lg["code"], home, away, r.date, r.date))
        rows = cur.fetchall()
        if not rows:
            unmatched.append((str(r.date)[:10], home, away, game_id))
        elif len(rows) > 1:
            ambiguous.append((str(r.date)[:10], home, away, game_id))
        elif rows[0][1] not in (None, str(game_id)):
            conflicts.append((rows[0][0], rows[0][1], game_id))
        else:
            links.append((rows[0][0], str(game_id), r.home_xg, r.away_xg, home, away))

    log.info("schedule mapping: %d linkable, %d unmatched, %d ambiguous, %d conflicting ids",
             len(links), len(unmatched), len(ambiguous), len(conflicts))
    for label, items in (("unmatched", unmatched), ("ambiguous", ambiguous), ("conflict", conflicts)):
        for item in items[:10]:
            log.info("  %s: %s", label, item)
    if args.dry_run:
        conn.close()
        return

    # 2. ids + team xG (fill-only).
    for match_id, game_id, home_xg, away_xg, home, away in links:
        cur.execute("UPDATE futbol.matches SET understat_game_id = %s "
                    "WHERE match_id = %s AND understat_game_id IS NULL", (game_id, match_id))
        for team, xg, is_home in ((home, home_xg, True), (away, away_xg, False)):
            tid = upsert_team(cur, team)
            cur.execute(
                """INSERT INTO futbol.team_match_stats (match_id, team_id, is_home, xg)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (match_id, team_id)
                   DO UPDATE SET xg = COALESCE(futbol.team_match_stats.xg, EXCLUDED.xg)""",
                (match_id, tid, is_home, _num(xg)))
            entities.record_source_stats(cur, match_id, tid, "understat", xg=_num(xg))
    conn.commit()
    log.info("linked %d matches, team xG filled", len(links))

    # 3. shots (this is the slow part: one Understat page per match).
    shots = us.read_shot_events().reset_index()
    log.info("Understat shots: %d rows", len(shots))
    cur.execute("SELECT understat_game_id, match_id FROM futbol.matches WHERE understat_game_id = ANY(%s)",
                ([str(g) for g in shots.game_id.dropna().unique()],))
    match_by_game = dict(cur.fetchall())
    inserted = skipped = 0
    for s in shots.itertuples():
        match_id = match_by_game.get(str(s.game_id))
        if match_id is None:
            skipped += 1
            continue
        team = entities.resolve_team("understat", s.team)
        tid = upsert_team(cur, team)
        pid = entities.link_player(cur, "understat", str(s.player_id), s.player, team)
        cur.execute(
            """INSERT INTO futbol.shots
                 (match_id, player_id, team_id, minute, x, y, situation, body_part, result, source_xg)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (match_id, player_id, minute, x, y, COALESCE(situation, ''), result)
               DO NOTHING""",
            (match_id, pid, tid, _int(s.minute), _num(s.location_x), _num(s.location_y),
             _clean(s.situation), _clean(s.body_part), _clean(s.result), _num(s.xg)))
        inserted += cur.rowcount
    conn.commit()
    conn.close()
    log.info("shots: %d inserted, %d skipped (game not linked)", inserted, skipped)


if __name__ == "__main__":
    main()
