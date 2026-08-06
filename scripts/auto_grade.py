"""
Automated grading.

    python scripts/auto_grade.py             # grade and void per the rules
    python scripts/auto_grade.py --dry-run   # report what would happen, write nothing

Grades every prediction whose match is final. Extends grader.grade_prediction
(built for 1X2/BTTS/TOTAL_GOALS) with observed-value lookups for the count
markets.

VOIDING
Predictions whose observed value never arrives used to sit ungraded forever,
retried nightly. They stayed in the ledger counted as predictions made while
being absent from every hit-rate figure, so the published record was quietly
computed over whichever subset happened to have stats. That is a selection
effect, not a rounding error: if the missing data correlates with anything —
a player dropped after poor form, say — the record is biased rather than
merely incomplete.

Two causes, two rules, because they are not the same kind of problem:

  player did not feature   The match is final and the player has no stats row
                           while other players in that match do. Definitive on
                           day one — waiting cannot change it, and an
                           anytime-scorer market voids when the player does not
                           appear rather than losing. Voided immediately.

  observed value missing   The team certainly played, or the whole match was
                           never ingested for players. The value may still
                           arrive via a source backfill, so these are left
                           pending for VOID_GRACE_DAYS before voiding.

Voiding only ever happens here, by rule, with the reason recorded. There is no
manual path, deliberately: voiding is the one operation that can remove a
prediction from the published rates, and it is only defensible while it cannot
be aimed at a particular result. Grading is also once-only — prediction_grades
is keyed on prediction_id — so a void cannot later be revised if the value
turns up, which is why the grace period is generous rather than tight.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2

from grading.grader import GRADER_VERSION, grade_prediction

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

VOID_GRACE_DAYS = 14

TEAM_STAT_COLUMN = {"CORNERS": "corners", "SOT": "shots_on_target"}
PLAYER_STAT_COLUMN = {"PLAYER_GOALS": "goals", "PLAYER_SAVES": "saves"}

VOID_PLAYER_ABSENT = "player_absent"
VOID_STAT_UNAVAILABLE = "stat_unavailable"
VOID_SUBJECT_MISSING = "subject_missing"

UNGRADED_SQL = """
SELECT p.prediction_id, p.match_id, p.market, p.side, p.line,
       p.subject_team_id, p.subject_player_id,
       m.status, m.home_goals, m.away_goals, m.kickoff_utc
FROM futbol.predictions p
JOIN futbol.matches m USING (match_id)
LEFT JOIN futbol.prediction_grades g USING (prediction_id)
WHERE g.prediction_id IS NULL AND m.status = 'final'
ORDER BY m.kickoff_utc
"""

INSERT_GRADE = """
INSERT INTO futbol.prediction_grades
    (prediction_id, outcome, actual_value, graded_at, grader_version, void_reason)
VALUES (%s, %s, %s, %s, %s, %s)
"""


def fetch_observed(cur, market: str, match_id: int,
                   subject_team_id, subject_player_id) -> dict:
    if market in TEAM_STAT_COLUMN and subject_team_id is not None:
        col = TEAM_STAT_COLUMN[market]
        cur.execute(
            f"SELECT {col} FROM futbol.team_match_stats "
            f"WHERE match_id = %s AND team_id = %s",
            (match_id, subject_team_id))
    elif market in PLAYER_STAT_COLUMN and subject_player_id is not None:
        col = PLAYER_STAT_COLUMN[market]
        cur.execute(
            f"SELECT {col} FROM futbol.player_match_stats "
            f"WHERE match_id = %s AND player_id = %s",
            (match_id, subject_player_id))
    else:
        return {}
    row = cur.fetchone()
    if row is None or row[0] is None:
        return {}
    return {"actual": float(row[0])}


def classify_missing(cur, row: dict) -> tuple[str, bool]:
    """
    Why is there no observed value, and is that answer already final?

    Returns (void_reason, decidable_now). decidable_now is True only when
    waiting cannot change the answer.
    """
    market = row["market"]

    if market in PLAYER_STAT_COLUMN:
        if row["subject_player_id"] is None:
            return VOID_SUBJECT_MISSING, False
        cur.execute(
            "SELECT 1 FROM futbol.player_match_stats WHERE match_id = %s "
            "AND player_id = %s", (row["match_id"], row["subject_player_id"]))
        if cur.fetchone() is not None:
            # They played; the specific column is simply empty.
            return VOID_STAT_UNAVAILABLE, False
        cur.execute(
            "SELECT 1 FROM futbol.player_match_stats WHERE match_id = %s LIMIT 1",
            (row["match_id"],))
        if cur.fetchone() is not None:
            # Other players in this match have rows, so the match was ingested
            # and this player genuinely did not feature.
            return VOID_PLAYER_ABSENT, True
        # No player rows at all — the match was never ingested for players, so
        # absence here says nothing about whether they played.
        return VOID_STAT_UNAVAILABLE, False

    if market in TEAM_STAT_COLUMN and row["subject_team_id"] is None:
        return VOID_SUBJECT_MISSING, False

    # The team unquestionably played; the value may yet be backfilled.
    return VOID_STAT_UNAVAILABLE, False


def run(conn, dry_run: bool = False, grace_days: int = VOID_GRACE_DAYS,
        verbose: bool = True) -> dict:
    now = datetime.now(timezone.utc)
    counts = {"graded": 0, "hit": 0, "miss": 0, "voided": 0, "pending": 0}
    void_reasons: dict[str, int] = {}

    with conn.cursor() as cur:
        cur.execute(UNGRADED_SQL)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        for row in rows:
            match = {k: row[k] for k in ("status", "home_goals", "away_goals")}
            pred = {"market": row["market"], "side": row["side"], "line": row["line"]}
            needs_stats = (row["market"] in TEAM_STAT_COLUMN
                           or row["market"] in PLAYER_STAT_COLUMN)

            reason = None
            if needs_stats:
                stats = fetch_observed(cur, row["market"], row["match_id"],
                                       row["subject_team_id"], row["subject_player_id"])
                if not stats:
                    reason, decidable_now = classify_missing(cur, row)
                    kickoff = row["kickoff_utc"]
                    if kickoff.tzinfo is None:
                        kickoff = kickoff.replace(tzinfo=timezone.utc)
                    age_days = (now - kickoff).days
                    if not decidable_now and age_days < grace_days:
                        counts["pending"] += 1
                        continue
                    outcome, actual = "void", None
                else:
                    outcome, actual = grade_prediction(pred, match, stats)
            else:
                outcome, actual = grade_prediction(pred, match, {})

            if outcome != "void":
                reason = None
            else:
                void_reasons[reason or "other"] = void_reasons.get(reason or "other", 0) + 1

            if not dry_run:
                cur.execute(INSERT_GRADE,
                            (row["prediction_id"], outcome, actual, now,
                             GRADER_VERSION, reason))

            counts["graded"] += 1
            if outcome in ("hit", "miss"):
                counts[outcome] += 1
            else:
                counts["voided"] += 1

        if not dry_run:
            conn.commit()

    if verbose:
        prefix = "[dry run] would grade" if dry_run else "graded"
        print(f"[{now.isoformat()}] auto_grade: {prefix} {counts['graded']} "
              f"({counts['hit']} hit, {counts['miss']} miss, "
              f"{counts['voided']} void), {counts['pending']} still pending")
        for reason, n in sorted(void_reasons.items(), key=lambda kv: -kv[1]):
            print(f"    void: {reason:<18} {n}")
        if dry_run:
            print("    nothing was written")

    counts["void_reasons"] = void_reasons
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be graded and voided, write nothing")
    ap.add_argument("--grace-days", type=int, default=VOID_GRACE_DAYS,
                    help="days to wait for a missing value before voiding")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    try:
        run(conn, dry_run=args.dry_run, grace_days=args.grace_days)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
