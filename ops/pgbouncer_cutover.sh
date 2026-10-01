#!/usr/bin/env bash
# pgbouncer_cutover.sh — route futbol-api's read path (FUTBOL_RO_DSN)
# through pgBouncer's futbol_ro alias instead of straight at Postgres.
#
# Usage (wherever you have kubectl access to the cluster):
#
#   ./ops/pgbouncer_cutover.sh                   # cut over
#   PGB_ROLLBACK=1 ./ops/pgbouncer_cutover.sh    # back to direct Postgres
#
# Scope: futbol-api only. futbol-web never connects to Postgres (it
# only talks to futbol-api-svc), and futbol-api only ever reads
# FUTBOL_RO_DSN, so this single env change is the whole cutover.
#
# How: a JSON patch on the futbol-api Deployment's env — the same
# front-end-identity pattern the CronJobs already use
# (k8s/cronjobs.yaml): futbol_ro_canary authenticates to pgBouncer,
# and pgBouncer's [databases] futbol_ro entry pins the backend to the
# real futbol_ro role. Nothing in futbol-secrets is touched.
#
# Why not edit futbol-secrets (the previous version of this script):
#   - pgBouncer itself reads FUTBOL_DSN/FUTBOL_RO_DSN from futbol-secrets
#     to build its backend config; repointing them at pgBouncer would
#     make it proxy to itself on its next restart, taking down the
#     CronJobs along with the API.
#   - The DSNs are libpq keyword format (host=... with no :port), so the
#     old "192.168.4.210:5432" substitution never matched — a silent
#     no-op that would have "succeeded" without cutting anything over.
#   - futbol-secrets is a SealedSecret; a hand-applied edit drifts from
#     k8s/futbol-secrets.sealed.yaml.
#
# Why not `kubectl apply -f k8s/webapp.yaml`: the manifest's image is
# :latest while the live Deployment is pinned to a commit tag by
# deploy-time `kubectl set image` — applying it would also roll the image.
#
# Safety: the API builds its connection pool at import time and /health
# runs SELECT 1, so a bad DSN leaves the new pod un-Ready. With 1
# replica and RollingUpdate 25%/25% (maxUnavailable rounds to 0), the
# old pod keeps serving until the new one is Ready — a bad cutover is a
# stuck rollout, not an outage.

set -euo pipefail

DEPLOY="deployment/futbol-api"
POOLED_DSN='host=futbol-pgbouncer-svc port=6432 dbname=futbol_ro user=futbol_ro_canary password=$(PGBOUNCER_RO_CANARY_PASSWORD)'

current_env() {
  kubectl get "$DEPLOY" -o json | jq -c '.spec.template.spec.containers[0].env'
}

if [[ "${PGB_ROLLBACK:-0}" == "1" ]]; then
  echo "=== ROLLBACK: FUTBOL_RO_DSN back to futbol-secrets (direct Postgres) ==="
  new_env=$(current_env | jq -c '
    map(select(.name != "PGBOUNCER_RO_CANARY_PASSWORD"))
    | map(if .name == "FUTBOL_RO_DSN"
          then {name: "FUTBOL_RO_DSN",
                valueFrom: {secretKeyRef: {name: "futbol-secrets", key: "FUTBOL_RO_DSN"}}}
          else . end)')
else
  echo "=== CUTOVER: FUTBOL_RO_DSN -> futbol-pgbouncer-svc:6432/futbol_ro ==="
  # Password var first: $(VAR) expansion only sees vars defined earlier.
  new_env=$(current_env | jq -c --arg dsn "$POOLED_DSN" '
    map(select(.name != "PGBOUNCER_RO_CANARY_PASSWORD" and .name != "FUTBOL_RO_DSN"))
    | [{name: "PGBOUNCER_RO_CANARY_PASSWORD",
        valueFrom: {secretKeyRef: {name: "futbol-secrets", key: "PGBOUNCER_RO_CANARY_PASSWORD"}}},
       {name: "FUTBOL_RO_DSN", value: $dsn}] + .')
fi

kubectl patch "$DEPLOY" --type=json \
  -p "[{\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/env\",\"value\":${new_env}}]"

if ! kubectl rollout status "$DEPLOY" --timeout=180s; then
  echo ">>> Rollout did not become Ready. Old pod is still serving."
  echo ">>> Undo with: kubectl rollout undo $DEPLOY"
  exit 1
fi

pod=$(kubectl get pods -l app=futbol-api --field-selector=status.phase=Running \
  --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}')
echo "--- $pod: last 20 log lines ---"
kubectl logs "$pod" --tail=20 || true

echo "=== done. Check https://futbol.josephbernal.com and pgBouncer's log"
echo "    (kubectl logs deploy/futbol-pgbouncer --tail=20) for futbol_ro_canary logins. ==="
