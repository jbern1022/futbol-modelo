"""
Nightly pipeline alerting (open ticket, per Todoist -- the ntfy half
that was blocked purely on not knowing the ntfy server URL/topic).
Checks futbol.pipeline_runs for any expected job with no successful
run in the last N hours (schedule is ~15-30 min apart, once daily --
26h default gives real slack before alerting) and POSTs to ntfy if so.
Read-only against the database; the only external effect is the
optional ntfy POST, gated on NTFY_URL/NTFY_TOPIC being set -- without
them this just prints and exits, same as check_model_drift.py.

    python scripts/check_pipeline_health.py
    python scripts/check_pipeline_health.py --stale-after-hours 30
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ops.ntfy import post_to_ntfy

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# Every job_name the three real CronJobs (k8s/cronjobs.yaml) actually
# write to pipeline_runs today. Kept as an explicit list, not a plain
# `SELECT DISTINCT job_name`, so a retired job doesn't alert forever --
# must be updated by hand if cronjobs.yaml's command chains change,
# same manual-sync discipline as sql/schema.sql vs sql/migrations/.
EXPECTED_JOBS = [
    "nightly_refresh:MLS", "nightly_refresh:EPL", "nightly_refresh:SERIE_A",
    "rebuild_features",
    "auto_slate:MLS", "auto_slate:EPL", "auto_slate:SERIE_A",
    "auto_grade",
]

LAST_SUCCESS_SQL = """
SELECT job_name, MAX(finished_at) AS last_success_at
FROM futbol.pipeline_runs
WHERE job_name = ANY(%s) AND status = 'success'
GROUP BY job_name
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale-after-hours", type=float, default=26.0,
                    help="Alert if a job's last success is older than this many hours, "
                         "or it has never succeeded (default 26)")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(LAST_SUCCESS_SQL, (EXPECTED_JOBS,))
            last_success = dict(cur.fetchall())
    finally:
        conn.close()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.stale_after_hours)
    stale = []

    print(f"Checking {len(EXPECTED_JOBS)} expected job(s) for a success in the last "
          f"{args.stale_after_hours}h:")
    for job_name in EXPECTED_JOBS:
        last = last_success.get(job_name)
        if last is None:
            print(f"  {job_name:24s} NEVER succeeded <-- STALE")
            stale.append((job_name, None))
        elif last < cutoff:
            age_hours = (now - last).total_seconds() / 3600
            print(f"  {job_name:24s} last success {age_hours:.1f}h ago <-- STALE")
            stale.append((job_name, last))
        else:
            age_hours = (now - last).total_seconds() / 3600
            print(f"  {job_name:24s} last success {age_hours:.1f}h ago -- OK")

    if not stale:
        print("All jobs healthy.")
        return

    lines = [f"{job_name}: {'never succeeded' if last is None else f'last success {last.isoformat()}'}"
            for job_name, last in stale]
    message = f"{len(stale)} pipeline job(s) stale (no success in {args.stale_after_hours}h):\n" + "\n".join(lines)
    print(message)
    post_to_ntfy(message, title="futbol-modelo: pipeline stale", priority="high")


if __name__ == "__main__":
    main()
