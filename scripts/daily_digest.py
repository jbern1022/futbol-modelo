"""
Daily digest (open ticket, per Todoist): "Yesterday's slate, graded" --
a real, visible artifact proving the system is alive without anyone
visiting the site. Summarizes everything graded in the last 24h
(by graded_at, not kickoff_utc -- when the ledger actually recorded
the result) and posts it to ntfy. Read-only against the database; if
NTFY_URL/NTFY_TOPIC aren't set, this just prints and exits, same as
check_model_drift.py and check_pipeline_health.py.

    python scripts/daily_digest.py
"""
import os
import sys

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ops.ntfy import post_to_ntfy

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
TRACK_RECORD_URL = "https://futbol.josephbernal.com/track-record"

# Same dedup key as v_graded_predictions -- a fixture slated twice
# shouldn't double-count the digest either.
GRADED_LAST_24H_SQL = """
WITH graded AS (
    SELECT g.outcome, l.code AS league,
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
    WHERE g.graded_at >= now() - interval '24 hours'
)
SELECT league, outcome, COUNT(*) AS n
FROM graded
WHERE dedup_rn = 1
GROUP BY league, outcome
ORDER BY league, outcome
"""


def main() -> None:
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(GRADED_LAST_24H_SQL)
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        message = "No predictions graded in the last 24h."
        print(message)
        post_to_ntfy(message, title="futbol-modelo: daily digest")
        return

    totals: dict[str, int] = {}
    by_league: dict[str, dict[str, int]] = {}
    for league, outcome, n in rows:
        totals[outcome] = totals.get(outcome, 0) + n
        by_league.setdefault(league, {})[outcome] = n

    hits = totals.get("hit", 0)
    misses = totals.get("miss", 0)
    voids = totals.get("void", 0)
    graded_for_rate = hits + misses  # void doesn't count toward hit rate
    hit_rate = hits / graded_for_rate if graded_for_rate else None

    lines = [f"Yesterday's slate, graded: {hits + misses + voids} predictions"]
    if hit_rate is not None:
        lines[0] += f", {hits} hits ({hit_rate:.1%})"
    for league in sorted(by_league):
        counts = by_league[league]
        parts = [f"{v} {k}" for k, v in sorted(counts.items())]
        lines.append(f"  {league}: {', '.join(parts)}")
    lines.append(f"Full breakdown: {TRACK_RECORD_URL}")

    message = "\n".join(lines)
    print(message)
    post_to_ntfy(message, title="futbol-modelo: daily digest")


if __name__ == "__main__":
    main()
