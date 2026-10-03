"""
Nightly pipeline alerting (open ticket, per Todoist -- the ntfy half
that was blocked purely on not knowing the ntfy server URL/topic).
Checks futbol.pipeline_runs for any expected job with no successful
run in the last N hours (schedule is ~15-30 min apart, once daily --
26h default gives real slack before alerting) and POSTs to ntfy if so.
Read-only against the database; the only external effect is the
optional ntfy POST, gated on NTFY_URL/NTFY_TOPIC being set -- without
them this just prints and exits, same as check_model_drift.py.

Also checks two slate invariants (ADR-012) against the ledger itself,
because job status alone missed the 2026-09-06 NFL freeze: nfl_slate
"succeeded" for four weeks while writing 0 rows.
  - missing slate: an NFL/soccer fixture kicking off within 48h with no
    live (non-voided) prediction. This job runs an hour after
    auto-slate, whose 3-day window already covers that range.
  - out of window: a live, ungraded prediction locked more than
    SLATE_WINDOW_DAYS before its kickoff (what a wide manual run makes).

    python scripts/check_pipeline_health.py
    python scripts/check_pipeline_health.py --stale-after-hours 30
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ops.json_logging import configure_json_logging
from ops.ntfy import post_to_ntfy
from predictions.slate_window import NO_LIVE_PREDICTION_SQL, SLATE_WINDOW_DAYS

log = configure_json_logging("check_pipeline_health")

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# Every job_name the five real CronJobs (k8s/cronjobs.yaml) actually
# write to pipeline_runs today. Kept as an explicit list, not a plain
# `SELECT DISTINCT job_name`, so a retired job doesn't alert forever --
# must be updated by hand if cronjobs.yaml's command chains change,
# same manual-sync discipline as sql/schema.sql vs sql/migrations/.
#
# Corrected 2026-09-22: this list predated LA_LIGA and everything added
# to the pipeline since (compute_team_ratings, nfl/nba slate+grade,
# simulate_bankroll, the odds CronJobs) -- confirmed against
# `SELECT DISTINCT job_name FROM futbol.pipeline_runs` on the live DB,
# so this monitor was blind to roughly half of what actually runs.
# nfl_slate/nba_slate carry a season in the job_name (same pattern as
# cronjobs.yaml's own hardcoded --season args) -- update these two
# alongside cronjobs.yaml when the season rolls over, or they'll read
# as permanently stale instead of raising a real alert.
EXPECTED_JOBS = [
    "nightly_refresh:MLS", "nightly_refresh:EPL", "nightly_refresh:SERIE_A", "nightly_refresh:LA_LIGA",
    "rebuild_features",
    "compute_team_ratings",
    "auto_slate:MLS", "auto_slate:EPL", "auto_slate:SERIE_A", "auto_slate:LA_LIGA",
    "nfl_slate:2026",
    "nba_slate:2026-27",
    "auto_grade",
    "simulate_bankroll",
    "odds:MLS", "odds:EPL", "odds:SERIE_A", "odds:LA_LIGA",
]

LAST_SUCCESS_SQL = """
SELECT job_name, MAX(finished_at) AS last_success_at
FROM futbol.pipeline_runs
WHERE job_name = ANY(%s) AND status = 'success'
GROUP BY job_name
"""

SLATED_LEAGUES = ("NFL", "EPL", "SERIE_A", "LA_LIGA", "MLS")

MISSING_SLATE_SQL = f"""
SELECT m.match_id, l.code, th.name || ' vs ' || ta.name, m.kickoff_utc
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
WHERE l.code IN {SLATED_LEAGUES}
  AND m.status = 'scheduled'
  AND m.kickoff_utc BETWEEN now() AND now() + interval '48 hours'
  AND {NO_LIVE_PREDICTION_SQL}
ORDER BY m.kickoff_utc
"""

OUT_OF_WINDOW_SQL = f"""
SELECT m.match_id, l.code, count(*) AS n_predictions,
       max(EXTRACT(DAY FROM m.kickoff_utc - p.created_at))::int AS max_days_early
FROM futbol.predictions p
JOIN futbol.matches m ON m.match_id = p.match_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
LEFT JOIN futbol.prediction_grades g ON g.prediction_id = p.prediction_id
WHERE l.code IN {SLATED_LEAGUES}
  AND m.status = 'scheduled'
  AND g.prediction_id IS NULL
  AND p.created_at < m.kickoff_utc - interval '{SLATE_WINDOW_DAYS} days'
GROUP BY m.match_id, l.code
ORDER BY m.match_id
"""


def slate_problems(cur) -> list[str]:
    cur.execute(MISSING_SLATE_SQL)
    missing = cur.fetchall()
    cur.execute(OUT_OF_WINDOW_SQL)
    early = cur.fetchall()
    problems = [f"no live slate: [{league}] {name} (match {mid}, kickoff {ko:%Y-%m-%d %H:%M}Z)"
                for mid, league, name, ko in missing]
    problems += [f"slate outside {SLATE_WINDOW_DAYS}-day window: [{league}] match {mid}, "
                 f"{n} prediction(s) locked up to {days} days early"
                 for mid, league, n, days in early]
    return problems


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
            problems = slate_problems(cur)
    finally:
        conn.close()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.stale_after_hours)
    stale = []

    log.info("checking expected jobs", extra={
        "n_expected_jobs": len(EXPECTED_JOBS), "stale_after_hours": args.stale_after_hours,
    })
    for job_name in EXPECTED_JOBS:
        last = last_success.get(job_name)
        if last is None:
            log.warning("job stale: never succeeded", extra={"job_name": job_name})
            stale.append((job_name, None))
        elif last < cutoff:
            age_hours = (now - last).total_seconds() / 3600
            log.warning("job stale", extra={"job_name": job_name, "age_hours": round(age_hours, 1)})
            stale.append((job_name, last))
        else:
            age_hours = (now - last).total_seconds() / 3600
            log.info("job healthy", extra={"job_name": job_name, "age_hours": round(age_hours, 1)})

    if problems:
        log.error("slate invariant broken", extra={"n_problems": len(problems), "problems": problems})
        post_to_ntfy(f"{len(problems)} slate problem(s):\n" + "\n".join(problems[:20]),
                     title="futbol-modelo: slate invariant broken", priority="high")
    else:
        log.info("slate invariants hold")

    if not stale:
        log.info("all jobs healthy")
        return

    lines = [f"{job_name}: {'never succeeded' if last is None else f'last success {last.isoformat()}'}"
            for job_name, last in stale]
    message = f"{len(stale)} pipeline job(s) stale (no success in {args.stale_after_hours}h):\n" + "\n".join(lines)
    log.error("pipeline stale", extra={"n_stale": len(stale), "stale_jobs": [j for j, _ in stale]})
    post_to_ntfy(message, title="futbol-modelo: pipeline stale", priority="high")


if __name__ == "__main__":
    main()
