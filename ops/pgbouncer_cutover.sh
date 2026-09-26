#!/usr/bin/env bash
# pgbouncer_cutover.sh — cut futbol-api / futbol-web over from a direct
# Postgres connection to pgBouncer (futbol-pgbouncer-svc:6432).
#
# Usage (run wherever you have kubectl + jq access to the cluster,
# e.g. the Mac or a cron on docker-host once kubectl is installed there):
#
#   ./ops/pgbouncer_cutover.sh api      # cut over futbol-api only (canary)
#   ./ops/pgbouncer_cutover.sh web      # cut over futbol-web only
#   ./ops/pgbouncer_cutover.sh api web  # both, api first, only proceeds
#                                        # to web if api's rollout succeeds
#
# What it does, per target:
#   1. Patches the shared futbol-secrets FUTBOL_DSN/FUTBOL_RO_DSN,
#      swapping the host:port from 192.168.4.210:5432 to
#      futbol-pgbouncer-svc:6432 — user/password/dbname untouched.
#      Done via a jq pipeline that decodes/edits/re-encodes in one
#      shot; the decoded secret is never printed or written to disk.
#   2. `kubectl rollout restart` + `kubectl rollout status --timeout=120s`
#      on the target Deployment (secret changes don't auto-restart pods).
#   3. Prints the last 20 log lines from the new pod so you can eyeball
#      a clean startup (no connection-refused / auth errors) before
#      moving to the next target.
#
# NOTE: futbol-secrets is shared by both api and web (and the 3
# CronJobs, already cut over). Patching it while cutting over "api"
# takes effect for web too the next time web's pods restart — but web
# is NOT restarted by this script unless you also pass "web". Don't
# run "api" alone and then separately restart web for an unrelated
# reason without expecting it to pick up the new (pgbouncer) DSN too.
#
# Rollback: re-run with PGB_ROLLBACK=1 to point back at the direct
# Postgres host, e.g.:
#   PGB_ROLLBACK=1 ./ops/pgbouncer_cutover.sh api web

set -euo pipefail

DIRECT_HOST="192.168.4.210:5432"
POOLED_HOST="futbol-pgbouncer-svc:6432"

if [[ "${PGB_ROLLBACK:-0}" == "1" ]]; then
  FROM="$POOLED_HOST"
  TO="$DIRECT_HOST"
  echo "=== ROLLBACK MODE: routing back to direct Postgres ==="
else
  FROM="$DIRECT_HOST"
  TO="$POOLED_HOST"
fi

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <api|web> [api|web ...]"
  exit 1
fi

patch_dsn() {
  echo "--- patching futbol-secrets: ${FROM} -> ${TO} ---"
  kubectl get secret futbol-secrets -o json \
    | jq --arg from "$FROM" --arg to "$TO" '
        .data |= with_entries(
          if (.key == "FUTBOL_DSN" or .key == "FUTBOL_RO_DSN") then
            .value |= (@base64d | sub($from; $to) | @base64)
          else . end
        )
      ' \
    | kubectl apply -f -
}

rollout_target() {
  local deployment="$1"
  echo "--- rolling out ${deployment} ---"
  kubectl rollout restart "deployment/${deployment}"
  kubectl rollout status "deployment/${deployment}" --timeout=120s

  echo "--- ${deployment}: last 20 log lines from the new pod ---"
  local pod
  pod=$(kubectl get pods -l "app=${deployment}" -o jsonpath='{.items[-1:].metadata.name}')
  kubectl logs "$pod" --tail=20 || true

  echo ">>> Check the log output above for connection/auth errors before continuing."
  echo ">>> If anything looks wrong, stop here and rerun with PGB_ROLLBACK=1 for this target."
}

patch_dsn

for target in "$@"; do
  case "$target" in
    api) rollout_target futbol-api ;;
    web) rollout_target futbol-web ;;
    *) echo "Unknown target: $target (expected 'api' or 'web')"; exit 1 ;;
  esac
done

echo "=== done. Verify https://futbol.josephbernal.com and /v1/pipeline-status before considering this final. ==="
