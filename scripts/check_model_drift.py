"""
Model drift / streak monitoring (open ticket, per Todoist): alert when
a market's realized hit rate diverges from its stated confidence by
more than a threshold, over a rolling window of its most recent graded
predictions (by kickoff_utc, not grading time -- chronological order
of the actual matches). Read-only against the database; the only
external effect is an optional ntfy POST if NTFY_URL/NTFY_TOPIC are
set in the environment -- without them, this just prints and exits,
so it's safe and useful to run by hand today even before alerting is
wired into a schedule.

    python scripts/check_model_drift.py                       # defaults
    python scripts/check_model_drift.py --window 50 --threshold 0.10
"""
import argparse
import os
import sys

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ops.ntfy import post_to_ntfy

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# Same dedup key as v_graded_predictions (a fixture slated twice
# shouldn't double-count), extended with kickoff_utc so drift is
# windowed by the chronological order of the actual matches, not
# whenever each one happened to get graded.
DRIFT_SQL = """
WITH graded AS (
    SELECT p.prediction_id, p.market, p.probability, g.outcome,
           l.code AS league, m.kickoff_utc,
           ROW_NUMBER() OVER (
               PARTITION BY p.match_id, p.market, p.side, p.line,
                            p.subject_team_id, p.subject_player_id
               ORDER BY p.prediction_id
           ) AS dedup_rn
    FROM futbol.predictions p
    JOIN futbol.prediction_grades g USING (prediction_id)
    JOIN futbol.matches m USING (match_id)
    JOIN futbol.seasons s USING (season_id)
    JOIN futbol.leagues l USING (league_id)
    WHERE g.outcome <> 'void'
),
deduped AS (
    SELECT * FROM graded WHERE dedup_rn = 1
),
windowed AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY league, market ORDER BY kickoff_utc DESC
           ) AS recency_rn
    FROM deduped
)
SELECT league, market,
       COUNT(*) AS n,
       ROUND(AVG(probability)::numeric, 4) AS avg_stated_prob,
       ROUND(AVG((outcome = 'hit')::int)::numeric, 4) AS realized_rate
FROM windowed
WHERE recency_rn <= %s
GROUP BY league, market
HAVING COUNT(*) >= %s
ORDER BY league, market
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=30,
                    help="Most recent N graded predictions per (league, market) to consider (default 30)")
    ap.add_argument("--min-n", type=int, default=15,
                    help="Minimum sample size before a market is even considered (default 15)")
    ap.add_argument("--threshold", type=float, default=0.15,
                    help="Absolute |stated - realized| that counts as drift (default 0.15)")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(DRIFT_SQL, (args.window, args.min_n))
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print(f"No (league, market) combo has {args.min_n}+ graded predictions in the last "
              f"{args.window} yet -- nothing to check.")
        return

    flagged = []
    print(f"Checked {len(rows)} (league, market) combo(s) with {args.min_n}+ of their last "
          f"{args.window} graded predictions:")
    for league, market, n, stated, realized in rows:
        drift = round(abs(stated - realized), 4)
        flag = " <-- DRIFT" if drift > args.threshold else ""
        print(f"  {league:10s} {market:14s} n={n:<4d} stated={stated:.4f} realized={realized:.4f} "
              f"diff={drift:.4f}{flag}")
        if drift > args.threshold:
            flagged.append((league, market, n, stated, realized, drift))

    if not flagged:
        print(f"No market exceeds the {args.threshold} drift threshold.")
        return

    lines = [f"{league} {market}: stated {stated:.1%} vs realized {realized:.1%} "
            f"(n={n}, diff {drift:.1%})" for league, market, n, stated, realized, drift in flagged]
    message = "Model drift detected:\n" + "\n".join(lines)
    print(message)
    post_to_ntfy(message, title="futbol-modelo: model drift detected")


if __name__ == "__main__":
    main()
