#!/bin/bash
# Cron-safe nightly runner — cron does NOT source .zshrc/.bash_profile, so
# configuration is loaded explicitly below. Refreshes MLS (idempotent) then
# grades anything newly-final.
#
# Configuration (never commit real values):
#   FUTBOL_DSN         Postgres connection string
#   API_FOOTBALL_KEY   API-Football key
#
# Provide them either as real environment variables, or in a .env file at the
# repository root (gitignored). Copy .env.example to .env and fill it in.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env if present. Values already in the environment win, so a cron entry
# or a secrets manager can override the file without editing it.
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
fi

missing=()
[[ -n "${FUTBOL_DSN:-}" ]]       || missing+=("FUTBOL_DSN")
[[ -n "${API_FOOTBALL_KEY:-}" ]] || missing+=("API_FOOTBALL_KEY")
if (( ${#missing[@]} )); then
    echo "ERROR: missing required configuration: ${missing[*]}" >&2
    echo "Set them in the environment or in $REPO_ROOT/.env (see .env.example)." >&2
    exit 1
fi
export FUTBOL_DSN API_FOOTBALL_KEY

export PYTHONPATH="${PYTHONPATH:-}${PYTHONPATH:+:}$REPO_ROOT/src"

if [[ -f "$REPO_ROOT/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.venv/bin/activate"
fi

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) nightly run start ==="
python -m ingestion.api_football backfill --league MLS --season 2026
python -m ingestion.api_football backfill --league EPL --season 2026 --primary
python -m ingestion.api_football backfill --league SERIE_A --season 2026 --primary
python scripts/auto_slate.py --league MLS --days 21
python scripts/auto_slate.py --league EPL --days 45
python scripts/auto_slate.py --league SERIE_A --days 45
python scripts/auto_grade.py
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) nightly run end ==="
