"""
One-off cleanup for ADR-012 (3-day slate window): voids every ungraded
NFL/soccer prediction that was locked more than SLATE_WINDOW_DAYS before
its kickoff, so the next slate run regenerates the fixture with current
injury, suspension and depth-chart news.

Never deletes or edits a prediction (ADR-002/ADR-008): each void is a new
prediction_grades row whose void_reason says why. Where the subject
player is known to be out, the reason names it first:

    NFL     nflverse weekly roster, latest week (RES + R01 -> IR, etc.)
    soccer  player_injuries 'out' row for this match only -- a player's
            'out' row for a different match (e.g. international duty
            before a break) says nothing about a fixture weeks later

Fixtures kicking off within --min-hours (default 6) are left alone, so
nothing loses its slate before the regenerating run gets to it.

    python scripts/void_stale_slates.py             # dry run, prints the plan
    python scripts/void_stale_slates.py --apply     # writes the void rows

Real incident (2026-10-02): a manual run on 2026-09-06 slated 180 NFL
games through December; De'Von Achane (torn ACL Week 3, on IR) still had
rushing-yards predictions for every remaining Dolphins game.
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2

from predictions.slate_window import (SLATE_WINDOW_DAYS, STALE_SLATE_GRADER_VERSION,
                                      nfl_reserve_reason, soccer_absence_reason,
                                      stale_void_reason)

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
LEAGUES = ("NFL", "EPL", "SERIE_A", "LA_LIGA", "MLS")

STALE_SQL = """
SELECT p.prediction_id, l.code, m.match_id, m.kickoff_utc, p.statement,
       p.subject_player_id, pl.nfl_player_id,
       EXTRACT(DAY FROM m.kickoff_utc - p.created_at)::int AS days_before
FROM futbol.predictions p
JOIN futbol.matches m ON m.match_id = p.match_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.model_versions mv ON mv.model_version_id = p.model_version_id
LEFT JOIN futbol.players pl ON pl.player_id = p.subject_player_id
LEFT JOIN futbol.prediction_grades g ON g.prediction_id = p.prediction_id
WHERE g.prediction_id IS NULL
  AND m.status = 'scheduled'
  AND m.kickoff_utc > now() + (%s || ' hours')::interval
  AND p.created_at < m.kickoff_utc - (%s || ' days')::interval
  AND l.code IN %s
  AND mv.model_name <> 'player_props_lineup_confirmed_v1'
ORDER BY m.kickoff_utc, p.prediction_id
"""

SOCCER_ABSENCE_SQL = """
SELECT reason FROM futbol.player_injuries
WHERE match_id = %s AND player_id = %s AND status = 'out'
"""


def nfl_roster_status(season: int) -> dict[str, tuple[str, str]]:
    """gsis_id (weekly rosters call it player_id) -> (status, status_description_abbr),
    from the latest week."""
    import nfl_data_py as nfl
    r = nfl.import_weekly_rosters([season])
    r = r[r["week"] == r["week"].max()]
    return {row.player_id: (row.status, row.status_description_abbr)
            for row in r.itertuples() if row.player_id}


def soccer_absence(cur, player_id: int, match_id: int) -> str | None:
    cur.execute(SOCCER_ABSENCE_SQL, (match_id, player_id))
    row = cur.fetchone()
    return soccer_absence_reason(row[0] or "unspecified") if row else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the void rows (default: dry run)")
    ap.add_argument("--min-hours", type=int, default=6,
                    help="leave fixtures kicking off within this many hours alone")
    ap.add_argument("--nfl-season", type=int, default=2026)
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(STALE_SQL, (str(args.min_hours), str(SLATE_WINDOW_DAYS), LEAGUES))
        rows = cur.fetchall()
        roster = nfl_roster_status(args.nfl_season) if any(r[1] == "NFL" for r in rows) else {}

        voids = []
        for (prediction_id, league, match_id, kickoff, statement,
             player_id, nfl_player_id, days_before) in rows:
            absence = None
            if league == "NFL" and nfl_player_id in roster:
                absence = nfl_reserve_reason(*roster[nfl_player_id])
            elif league != "NFL" and player_id is not None:
                absence = soccer_absence(cur, player_id, match_id)
            voids.append((prediction_id, league, match_id, statement,
                          stale_void_reason(days_before, absence), absence))

        by_league = Counter(v[1] for v in voids)
        fixtures = Counter(league for league, _ in {(v[1], v[2]) for v in voids})
        print(f"{len(voids)} stale prediction(s) across {sum(fixtures.values())} fixture(s)")
        for league in LEAGUES:
            if by_league[league]:
                print(f"  {league:8} {by_league[league]:5} predictions, {fixtures[league]:3} fixtures")
        flagged = [v for v in voids if v[5]]
        print(f"\n{len(flagged)} with a named absence:")
        for _, league, match_id, statement, reason, _ in flagged:
            print(f"  [{league} {match_id}] {statement} -- {reason}")
        if voids:
            print(f"\nexample generic reason: {voids[0][4]}")

        if not args.apply:
            print("\ndry run -- nothing written (pass --apply to void)")
            conn.close()
            return

        cur.executemany(
            """INSERT INTO futbol.prediction_grades
                   (prediction_id, outcome, actual_value, graded_at, grader_version, void_reason)
               VALUES (%s, 'void', NULL, now(), %s, %s)""",
            [(v[0], STALE_SLATE_GRADER_VERSION, v[4]) for v in voids])
        conn.commit()
        print(f"\nvoided {len(voids)} prediction(s)")
    conn.close()


if __name__ == "__main__":
    main()
