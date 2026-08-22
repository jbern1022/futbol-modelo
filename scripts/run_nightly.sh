#!/bin/bash
# NOT what's deployed. Production runs as three separate k8s CronJobs
# (see k8s/cronjobs.yaml) on the cluster, each with its own
# pipeline_runs tracking (src/ops/pipeline_run.py) -- this script is a
# local-Mac-only equivalent (hardcoded path below, meant to run from a
# personal crontab via .venv), useful for manually replaying the same
# steps by hand but not part of the real automated pipeline.
#
# Cron-safe nightly runner — cron does NOT source .zshrc/.bash_profile, so
# FUTBOL_DSN and API_FOOTBALL_KEY must be exported before this script runs
# (e.g. from a gitignored env file sourced by the crontab entry itself).
# Never hardcode real values here — this script is checked into a public
# repo. Refreshes MLS (idempotent) then grades anything newly-final.

set -e

: "${FUTBOL_DSN:?FUTBOL_DSN must be set in the environment before running}"
: "${API_FOOTBALL_KEY:?API_FOOTBALL_KEY must be set in the environment before running}"
export PYTHONPATH="/Users/joebernal/Documents/Projects/Futbol-Modelo/futbol-modelo/src"

cd /Users/joebernal/Documents/Projects/Futbol-Modelo/futbol-modelo
source .venv/bin/activate

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) nightly run start ==="
python -m ingestion.api_football backfill --league MLS --season 2026
python -m ingestion.api_football backfill --league EPL --season 2026 --primary
python -m ingestion.api_football backfill --league SERIE_A --season 2026 --primary
python scripts/auto_slate.py --league MLS --days 21
python scripts/auto_slate.py --league EPL --days 45
python scripts/auto_slate.py --league SERIE_A --days 45
python scripts/auto_grade.py
python scripts/data_quality_checks.py
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) nightly run end ==="
