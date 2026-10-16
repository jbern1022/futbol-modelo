"""
Withdraw the live MLS shots-on-target predictions on fixtures slated BEFORE the
2026-10-16 pause (Todoist 6hmV8gr2VhFrWGh7, registry 2026-10-15 "Result, an xG-free
props model for MLS").

Why: the pooled props model never trained on MLS (no xG, so every MLS row is dropped
as incomplete) but scored MLS with xG missing, and under-predicted MLS shots on
target by 11% to 16%. The pause (commit 1641002) stops NEW MLS SOT picks; a fixture
gets one slate ever, so fixtures already slated would otherwise still publish and
grade the biased picks.

What it does, and does not do (ADR-002/005/008): it never edits or deletes a
prediction. For each live MLS SOT prediction on a fixture that has not kicked off it
inserts ONE new prediction_grades row: outcome 'void', void_reason naming the cause.
prediction_grades is immutable (trigger), so a void cannot be undone. Only
predictions with NO grade yet and whose match is still 'scheduled' and starts more
than --min-hours away are touched; already-graded MLS SOT rows (the historical track
record) are left exactly as they are. Voiding happens before kickoff, so no outcome
is known and nothing is selected on results.

    python scripts/void_mls_sot.py                       # dry run, prints the plan
    python scripts/void_mls_sot.py --apply --expect 77   # writes; aborts if the count differs
"""
import argparse
import os
import sys
from collections import Counter

import psycopg2

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
GRADER_VERSION = "mls-sot-pause-void-1.0"
VOID_REASON = ("MLS shots-on-target paused 2026-10-16: the pooled props model never trained on MLS and "
               "under-predicted MLS shots on target by 11-16% (registry 2026-10-15, Todoist 6hmV8gr2VhFrWGh7). "
               "Withdrawn before kickoff; no outcome was known when voided.")

PLAN_SQL = """
SELECT p.prediction_id, m.match_id, m.kickoff_utc, th.name, ta.name, p.statement
FROM futbol.predictions p
JOIN futbol.matches m ON m.match_id = p.match_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
LEFT JOIN futbol.prediction_grades g ON g.prediction_id = p.prediction_id
WHERE l.code = 'MLS' AND p.market = 'SOT'
  AND g.prediction_id IS NULL
  AND m.status = 'scheduled'
  AND m.kickoff_utc > now() + (%s || ' hours')::interval
ORDER BY m.kickoff_utc, p.prediction_id
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the void rows (default: dry run)")
    ap.add_argument("--expect", type=int, help="abort unless exactly this many predictions are in scope")
    ap.add_argument("--min-hours", type=int, default=1,
                    help="leave fixtures kicking off within this many hours alone")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(PLAN_SQL, (str(args.min_hours),))
        rows = cur.fetchall()
        per_fixture = Counter((r[1], r[2], r[3], r[4]) for r in rows)
        print(f"{len(rows)} live MLS SOT prediction(s) on {len(per_fixture)} fixture(s) "
              f"(kickoff more than {args.min_hours}h away)")
        for (match_id, kickoff, home, away), n in sorted(per_fixture.items(), key=lambda kv: kv[0][1]):
            print(f"  {match_id}  {kickoff:%Y-%m-%d %H:%M}  {home} v {away}: {n}")
        print(f"\ngrader_version: {GRADER_VERSION}\nvoid_reason:    {VOID_REASON}")

        if args.expect is not None and len(rows) != args.expect:
            print(f"\nABORT: expected {args.expect} predictions in scope, found {len(rows)}. Nothing written.")
            conn.close()
            sys.exit(2)
        if not args.apply:
            print("\ndry run -- nothing written (pass --apply to void)")
            conn.close()
            return

        cur.executemany(
            """INSERT INTO futbol.prediction_grades
                   (prediction_id, outcome, actual_value, graded_at, grader_version, void_reason)
               VALUES (%s, 'void', NULL, now(), %s, %s)""",
            [(r[0], GRADER_VERSION, VOID_REASON) for r in rows])
        cur.execute("SELECT count(*) FROM futbol.prediction_grades WHERE grader_version = %s", (GRADER_VERSION,))
        written = cur.fetchone()[0]
        if written != len(rows):
            conn.rollback()
            print(f"ABORT: wrote {written} rows but planned {len(rows)}; rolled back.")
            conn.close()
            sys.exit(3)
        conn.commit()
        print(f"\nvoided {written} prediction(s)")
    conn.close()


if __name__ == "__main__":
    main()
