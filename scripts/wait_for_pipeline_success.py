"""
Blocks a CronJob's command chain until an upstream job's most recent
futbol.pipeline_runs row is a recent 'success', or exits non-zero after a
timeout. Turns the "grading ran before ingest finished" failure class
(see Todoist: "Orchestrate ingest -> features -> slate -> grade as
dependent steps") from a silent, timing-based race into a loud one.

Checks the LAST job_name in an upstream CronJob's `&&`-chained command
list as its completion signal -- the chain only reaches that step if
every command before it exited 0, so there's no need to track every
intermediate step separately. E.g. futbol-nightly-refresh's chain ends
with compute_team_ratings; futbol-auto-slate's ends with
nba_slate:<season>; futbol-auto-grade's ends with simulate_bankroll.

    python scripts/wait_for_pipeline_success.py --job compute_team_ratings
    python scripts/wait_for_pipeline_success.py --job-prefix nba_slate: --within-minutes 180
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ops.ntfy import post_to_ntfy

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")


def get_last_success(cur, job_name: str | None = None, job_prefix: str | None = None):
    """Returns the most recent finished_at for a successful run matching
    job_name (exact) or job_prefix (LIKE 'prefix%'), or None."""
    if job_name:
        cur.execute(
            "SELECT MAX(finished_at) FROM futbol.pipeline_runs "
            "WHERE job_name = %s AND status = 'success'", (job_name,))
    else:
        cur.execute(
            "SELECT MAX(finished_at) FROM futbol.pipeline_runs "
            "WHERE job_name LIKE %s AND status = 'success'", (job_prefix + "%",))
    row = cur.fetchone()
    return row[0] if row else None


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--job", help="exact job_name to wait for")
    g.add_argument("--job-prefix", help="job_name prefix to wait for (e.g. 'nba_slate:')")
    ap.add_argument("--within-minutes", type=float, default=180.0,
                     help="only count a success finished within this many minutes (default 180)")
    ap.add_argument("--poll-seconds", type=float, default=20.0,
                     help="seconds between checks (default 20)")
    ap.add_argument("--timeout-minutes", type=float, default=45.0,
                     help="give up and exit non-zero after this long (default 45)")
    args = ap.parse_args()

    label = args.job or f"{args.job_prefix}*"
    deadline = time.monotonic() + args.timeout_minutes * 60
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=args.within_minutes)

    print(f"Waiting for a recent success of '{label}' (finished after {cutoff.isoformat()}), "
          f"timeout {args.timeout_minutes}m")

    last_seen = None
    while True:
        conn = psycopg2.connect(DSN)
        try:
            with conn.cursor() as cur:
                last_seen = get_last_success(cur, args.job, args.job_prefix)
        finally:
            conn.close()

        if last_seen is not None and last_seen >= cutoff:
            print(f"OK: '{label}' last succeeded at {last_seen.isoformat()}")
            return

        if time.monotonic() >= deadline:
            msg = (f"Timed out after {args.timeout_minutes}m waiting for '{label}' to "
                   f"succeed (last success: {last_seen.isoformat() if last_seen else 'never'})")
            print(msg)
            post_to_ntfy(msg, title="futbol-modelo: pipeline gate timeout", priority="high")
            raise SystemExit(1)

        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
