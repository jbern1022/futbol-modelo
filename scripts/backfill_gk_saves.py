"""
Fill goalkeeper saves / goals conceded on EXISTING player_match_stats rows that
came from the FBref-style loader (Todoist 6hhr9v5x6V3hVWR7).

Why not backfill_player_match_stats.py: that script (load_fixture_players)
resolves players ONLY by api_football_id. The EPL 2021-22, 2022-23 and 2025-26
rows were written by another loader (every player has an fbref_id and no
api_football_id, position is NULL). Re-fetching them through
load_fixture_players would create NEW players keyed by API id and a second set
of player_match_stats rows for the same match (the ON CONFLICT key is
(match_id, player_id), which would not collide), double-counting minutes and
shots. This script instead updates the existing rows in place.

For each final match whose rows have no goalkeeper saves it makes ONE call
(fixtures/players), takes every API goalkeeper that played, finds the existing
row for the same match and team whose player name matches (accent-insensitive;
the API gives "H. Lloris", the DB "Hugo Lloris": same surname and same first
initial, unique within the team), and sets saves and goals_conceded where they
are NULL. It never inserts, never creates players, never overwrites a value.
A goalkeeper it cannot match uniquely is reported and skipped.

Dry run by default: calls the API, reads the DB, prints the match rate and what
it would write; writes nothing.

    python scripts/backfill_gk_saves.py --league EPL --seasons 2022-23 --limit 15
    python scripts/backfill_gk_saves.py --league EPL --seasons 2021-22 2022-23 2025-26 --execute
"""
import argparse
import logging
import os
import sys
import unicodedata
from collections import Counter

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ingestion.api_football import _get, _session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
COMMIT_EVERY = 20

PENDING_SQL = """
SELECT m.match_id, m.api_football_fixture_id, m.home_team_id, m.away_team_id, th.api_football_id, s.label
FROM futbol.matches m
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.teams th ON th.team_id = m.home_team_id
WHERE l.code = %s AND m.status = 'final'
  AND m.api_football_fixture_id IS NOT NULL AND th.api_football_id IS NOT NULL
  AND s.label = ANY(%s)
  AND EXISTS (SELECT 1 FROM futbol.player_match_stats p WHERE p.match_id = m.match_id)
  AND NOT EXISTS (SELECT 1 FROM futbol.player_match_stats p WHERE p.match_id = m.match_id AND p.saves IS NOT NULL)
ORDER BY m.kickoff_utc
"""

ROWS_SQL = """
SELECT p.player_id, pl.full_name FROM futbol.player_match_stats p
JOIN futbol.players pl ON pl.player_id = p.player_id
WHERE p.match_id = %s AND p.team_id = %s AND p.minutes > 0
"""


def norm(name: str) -> list[str]:
    """Accent-insensitive lowercase tokens, punctuation dropped."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    for ch in ".'-":
        s = s.replace(ch, " ")
    return [t for t in s.split() if t]


def match_name(api_name: str, candidates: list[tuple[int, str]]) -> int | None:
    """Unique candidate whose surname matches and whose first initial matches.
    Falls back to a unique surname-only match. None if zero or ambiguous."""
    a = norm(api_name)
    if not a:
        return None
    a_last, a_init = a[-1], a[0][0]
    strict, loose = [], []
    for pid, full in candidates:
        c = norm(full)
        if not c:
            continue
        surname_hit = a_last in c            # handles "de Gea" style compound surnames
        if surname_hit and c[0][0] == a_init:
            strict.append(pid)
        elif surname_hit:
            loose.append(pid)
    if len(strict) == 1:
        return strict[0]
    if not strict and len(loose) == 1:
        return loose[0]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["EPL", "SERIE_A", "LA_LIGA", "BUNDESLIGA"])
    ap.add_argument("--seasons", nargs="+", required=True)
    ap.add_argument("--limit", type=int, help="process at most this many matches")
    ap.add_argument("--execute", action="store_true", help="write (default: dry run)")
    ap.add_argument("--max-consecutive-failures", type=int, default=5)
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(PENDING_SQL, (args.league, args.seasons))
    pending = cur.fetchall()
    if args.limit:
        pending = pending[: args.limit]
    log.info("%d matches with player rows and no goalkeeper saves (%s)%s",
             len(pending), ", ".join(args.seasons), "" if args.execute else " [DRY RUN]")

    session = _session()
    stats, fails = Counter(), 0
    for i, (match_id, fixture_id, home_id, away_id, home_api, label) in enumerate(pending, start=1):
        try:
            resp = _get(session, "fixtures/players", {"fixture": fixture_id})
            fails = 0
        except Exception as e:  # noqa: BLE001
            fails += 1
            stats["fixture_failed"] += 1
            log.warning("fixture %s failed: %s", fixture_id, e)
            if fails >= args.max_consecutive_failures:
                log.error("stopping after %d consecutive failures", fails)
                break
            continue
        for block in resp:
            tid = home_id if block["team"]["id"] == home_api else away_id
            cur.execute(ROWS_SQL, (match_id, tid))
            cands = cur.fetchall()
            for p in block["players"]:
                st = p["statistics"][0] if p["statistics"] else {}
                games, goals = st.get("games") or {}, st.get("goals") or {}
                if games.get("position") != "G" or not (games.get("minutes") or 0):
                    continue
                stats["gk_seen"] += 1
                pid = match_name(p["player"]["name"], cands)
                if pid is None:
                    stats["gk_unmatched"] += 1
                    log.info("unmatched GK %r in match %s (%s)", p["player"]["name"], match_id, label)
                    continue
                stats["gk_matched"] += 1
                if goals.get("saves") is None:
                    stats["api_saves_null"] += 1
                if args.execute:
                    cur.execute(
                        """UPDATE futbol.player_match_stats
                           SET saves = COALESCE(saves, %s), goals_conceded = COALESCE(goals_conceded, %s)
                           WHERE match_id = %s AND player_id = %s""",
                        (goals.get("saves"), goals.get("conceded"), match_id, pid))
                    stats["rows_updated"] += cur.rowcount
                    cur.execute("UPDATE futbol.players SET position = 'G' WHERE player_id = %s AND position IS NULL",
                                (pid,))
        if args.execute and i % COMMIT_EVERY == 0:
            conn.commit()
    if args.execute:
        conn.commit()
    conn.close()
    seen = stats["gk_seen"]
    print(f"\nmatches processed: {i if pending else 0}   goalkeepers seen: {seen}   "
          f"matched {stats['gk_matched']} ({stats['gk_matched'] / seen:.1%})   "
          f"unmatched {stats['gk_unmatched']}   API saves null {stats['api_saves_null']}   "
          f"failed fixtures {stats['fixture_failed']}" if seen else "no goalkeepers seen")
    if args.execute:
        print(f"rows updated: {stats['rows_updated']}")
    else:
        print("DRY RUN: nothing written. Re-run with --execute to write.")


if __name__ == "__main__":
    main()
