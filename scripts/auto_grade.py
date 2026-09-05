"""
Automated grading — finds every prediction whose match is now final but
hasn't been graded yet, and grades it. Extends grader.py's grade_prediction
(built for 1X2/BTTS/TOTAL_GOALS) with real observed-value lookups for
CORNERS/SOT, which didn't exist when that scaffold was written.

    python scripts/auto_grade.py
"""
import os
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2
import psycopg2.extensions

from grading.grader import grade_prediction, GRADER_VERSION
from ops.pipeline_run import track_run

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

UNGRADED_SQL = """
SELECT p.prediction_id, p.match_id, p.market, p.side, p.line,
       p.subject_team_id, p.subject_player_id,
       m.status, m.home_score, m.away_score
FROM futbol.predictions p
JOIN futbol.matches m USING (match_id)
LEFT JOIN futbol.prediction_grades g USING (prediction_id)
WHERE g.prediction_id IS NULL AND m.status = 'final';
"""

TEAM_STAT_COLUMN = {"CORNERS": "corners", "SOT": "shots_on_target"}
PLAYER_STAT_COLUMN = {"PLAYER_GOALS": "goals", "PLAYER_SAVES": "saves"}


def fetch_observed(cur: psycopg2.extensions.cursor, market: str, match_id: int,
                   subject_team_id: int | None,
                   subject_player_id: int | None) -> dict[str, float]:
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


def main() -> None:
    with track_run("auto_grade") as set_rows_written:
        conn = psycopg2.connect(DSN)
        graded, voided, skipped = 0, 0, 0
        with conn.cursor() as cur:
            cur.execute(UNGRADED_SQL)
            cols = [d[0] for d in cur.description]
            rows: list[dict[str, Any]] = [dict(zip(cols, r)) for r in cur.fetchall()]

            for row in rows:
                match = {"status": row["status"], "home_score": row["home_score"],
                         "away_score": row["away_score"]}
                pred = {"market": row["market"], "side": row["side"], "line": row["line"]}

                needs_stats = row["market"] in TEAM_STAT_COLUMN or row["market"] in PLAYER_STAT_COLUMN
                if needs_stats:
                    stats = fetch_observed(cur, row["market"], row["match_id"],
                                           row["subject_team_id"], row["subject_player_id"])
                    if not stats:
                        skipped += 1
                        continue
                else:
                    stats = {}

                outcome, actual = grade_prediction(pred, match, stats)
                cur.execute(
                    """INSERT INTO futbol.prediction_grades
                         (prediction_id, outcome, actual_value, graded_at, grader_version)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (row["prediction_id"], outcome, actual,
                     datetime.now(timezone.utc), GRADER_VERSION))
                graded += 1
                if outcome == "void":
                    voided += 1

            conn.commit()
        conn.close()
        set_rows_written(graded)
        print(f"[{datetime.now(timezone.utc).isoformat()}] auto_grade: "
              f"{graded} graded ({voided} void), {skipped} skipped (no stats yet)")


if __name__ == "__main__":
    main()
