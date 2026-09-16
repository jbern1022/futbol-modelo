#!/bin/bash
# Historical FBref player-stats backfill (2026-09-16 decision -- "go ahead").
# Understat/xG is already loaded for all these league-seasons (checked live
# against the DB first), so this only runs loader.py's FBref stage
# (--skip-understat) -- the slow part (~47s/match measured on a full-season
# test run, ~5h/league-season). La Liga excluded: it has no historical match
# rows in the DB yet (only 2025-26), so FBref stats have nothing to attach
# to via _find_match until La Liga's match history is backfilled separately.
#
# Sequential, not parallel -- deliberately, to stay a well-behaved single
# scraper against FBref rather than hitting it from multiple processes at
# once. Continues past a season that ultimately fails after loader.py's own
# 3-attempt retry, so one bad season doesn't block the rest of the queue.
set -uo pipefail
cd "$(dirname "$0")/.."

set -a
source .env
set +a
export PATH="$PWD/.venv/bin:$PATH"

LOG=backfill_historical_fbref.log
SEASONS="2122 2223 2324 2425 2526"

echo "=== historical FBref backfill started $(date -u) ===" >> "$LOG"

for LEAGUE in EPL SERIE_A; do
  for SEASON in $SEASONS; do
    echo "--- $LEAGUE $SEASON: starting $(date -u) ---" >> "$LOG"
    python -m ingestion.loader backfill --league "$LEAGUE" --seasons "$SEASON" \
      --skip-understat >> "$LOG" 2>&1
    STATUS=$?
    echo "--- $LEAGUE $SEASON: finished $(date -u) exit=$STATUS ---" >> "$LOG"
  done
done

echo "=== historical FBref backfill complete $(date -u) ===" >> "$LOG"
