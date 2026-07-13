#!/bin/bash
# Cron-safe nightly runner — explicit env vars since cron does NOT source
# .zshrc/.bash_profile. Refreshes MLS (idempotent) then grades anything
# newly-final.

set -e

export FUTBOL_DSN="host=192.168.4.210 dbname=futbol user=futbol password=Futbol2026Lab"
export API_FOOTBALL_KEY="3fc3baf718194dbddaea28de4a5ff578"
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
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) nightly run end ==="
