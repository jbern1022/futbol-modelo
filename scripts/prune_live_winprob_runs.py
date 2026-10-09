"""
Retention for the per-minute live win-probability poller's health
telemetry (Todoist: "retention rule for live_winprob pipeline_runs rows",
data audit 2026-10-03). The poller writes ~5,760 pipeline_runs rows a
day (~2M/yr, ~400 MB). They only say whether a tick ran, not what it
predicted: the series itself lives in futbol.live_win_probability and is
never touched here.

Deletes live_winprob:* rows older than --keep-days (default 30). Every
other job's history is kept. Dry run by default; pass --execute to delete.

    python scripts/prune_live_winprob_runs.py              # dry run
    python scripts/prune_live_winprob_runs.py --execute
    python scripts/prune_live_winprob_runs.py --keep-days 14 --execute
"""
import argparse
import os

import psycopg2

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

JOB_NAME_LIKE = "live_winprob:%"
DEFAULT_KEEP_DAYS = 30

COUNT_SQL = """
SELECT COUNT(*) FROM futbol.pipeline_runs
WHERE job_name LIKE %s AND started_at < now() - (%s || ' days')::interval
"""

DELETE_SQL = """
DELETE FROM futbol.pipeline_runs
WHERE job_name LIKE %s AND started_at < now() - (%s || ' days')::interval
"""


def prune(cur, keep_days: int, execute: bool) -> int:
    """Rows eligible for deletion; deletes them only when execute is True."""
    if keep_days < 1:
        raise ValueError(f"keep-days must be at least 1, got {keep_days}")
    params = (JOB_NAME_LIKE, str(keep_days))
    cur.execute(COUNT_SQL, params)
    n = cur.fetchone()[0]
    if execute and n:
        cur.execute(DELETE_SQL, params)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-days", type=int, default=DEFAULT_KEEP_DAYS)
    ap.add_argument("--execute", action="store_true", help="delete (default: dry run)")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        n = prune(cur, args.keep_days, args.execute)
    if args.execute:
        conn.commit()
        print(f"deleted {n} live_winprob pipeline_runs row(s) older than {args.keep_days} days")
    else:
        conn.rollback()
        print(f"dry run: {n} live_winprob pipeline_runs row(s) older than "
              f"{args.keep_days} days (pass --execute to delete)")
    conn.close()


if __name__ == "__main__":
    main()
