#!/usr/bin/env bash
# deploy.sh — push a tagged image to Gitea and roll it out in k3s.
#
# Usage (run on docker-host or any machine with docker + kubectl access):
#
#   ./ops/deploy.sh futbol-api <SHA>
#   ./ops/deploy.sh futbol-web <SHA>
#   ./ops/deploy.sh futbol-modelo <SHA>    # updates all three CronJobs
#
# <SHA> is the short image digest you want to deploy (e.g. e9ad60d).
# The script builds the image, tags it :<SHA>, pushes to the Gitea
# registry, then updates the relevant k8s workloads and waits for
# rollout to complete.
#
# One-time prerequisites (see CLAUDE.md):
#   kubectl create secret docker-registry gitea-registry \
#     --docker-server=gitea.josephbernal.com \
#     --docker-username=joe \
#     --docker-password=<GITEA_TOKEN>
#   docker login gitea.josephbernal.com   # on docker-host

set -euo pipefail

REGISTRY="gitea.josephbernal.com/joe"
USAGE="Usage: $0 <futbol-api|futbol-web|futbol-modelo> <sha>"

TARGET="${1:-}"
SHA="${2:-}"

[[ -z "$TARGET" || -z "$SHA" ]] && { echo "$USAGE"; exit 1; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

build_and_push() {
    local name="$1"
    local dockerfile="$2"
    local context="$3"

    echo "==> Building $name ..."
    # --platform linux/amd64 is required, not cosmetic: every real
    # workload (futbol-api, futbol-web, all 3 CronJobs) is nodeSelector-
    # pinned to k3s-control-plane, which is amd64 -- building on an
    # Apple Silicon Mac without this produces an arm64 image that pulls
    # fine but fails at container start with "exec format error" (a
    # real incident, 2026-09-14: silently masked for hours by an
    # unrelated DNS outage blocking the pull entirely, only surfaced
    # once that was fixed and the pull actually succeeded).
    docker build --provenance=false --platform linux/amd64 \
        -t "${REGISTRY}/${name}:${SHA}" \
        -t "${REGISTRY}/${name}:latest" \
        -f "${REPO_ROOT}/${dockerfile}" \
        "${REPO_ROOT}/${context}"

    echo "==> Pushing ${name}:${SHA} and :latest ..."
    docker push "${REGISTRY}/${name}:${SHA}"
    docker push "${REGISTRY}/${name}:latest"
}

rollout_deployment() {
    local deployment="$1"
    local container="$2"
    local image="$3"

    echo "==> Rolling out ${deployment} ..."
    kubectl set image "deployment/${deployment}" "${container}=${image}"
    kubectl rollout status "deployment/${deployment}" --timeout=120s
}

patch_cronjob() {
    local cronjob="$1"
    local container="$2"
    local image="$3"

    echo "==> Patching CronJob ${cronjob} ..."
    kubectl patch cronjob "${cronjob}" \
        -p "{\"spec\":{\"jobTemplate\":{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"${container}\",\"image\":\"${image}\"}]}}}}}}"
}

case "$TARGET" in
    futbol-api)
        build_and_push "futbol-api" "Dockerfile.api" "."
        rollout_deployment "futbol-api" "futbol-api" "${REGISTRY}/futbol-api:${SHA}"
        ;;

    futbol-web)
        build_and_push "futbol-web" "web/Dockerfile" "web"
        rollout_deployment "futbol-web" "futbol-web" "${REGISTRY}/futbol-web:${SHA}"
        ;;

    futbol-modelo)
        build_and_push "futbol-modelo" "Dockerfile" "."
        patch_cronjob "futbol-nightly-refresh" "refresh"      "${REGISTRY}/futbol-modelo:${SHA}"
        patch_cronjob "futbol-auto-slate"      "auto-slate"   "${REGISTRY}/futbol-modelo:${SHA}"
        patch_cronjob "futbol-auto-grade"      "auto-grade"   "${REGISTRY}/futbol-modelo:${SHA}"
        # Found 2026-09-21: these two were missing from this list, so they
        # stayed on :latest with imagePullPolicy: IfNotPresent -- pushing a
        # new :latest silently did nothing for them once any image had ever
        # been cached under that tag on the node. Confirmed live: while the
        # three CronJobs above tracked the current SHA correctly, these two
        # were still sitting on a stale :latest days after a real deploy.
        patch_cronjob "futbol-odds-daily"      "odds-daily"   "${REGISTRY}/futbol-modelo:${SHA}"
        patch_cronjob "futbol-odds-intraday"   "odds-intraday" "${REGISTRY}/futbol-modelo:${SHA}"
        # Added with futbol-pipeline-health (k8s/cronjobs.yaml, 2026-09-22)
        # -- same stale-:latest trap the two odds CronJobs hit above.
        patch_cronjob "futbol-pipeline-health" "pipeline-health" "${REGISTRY}/futbol-modelo:${SHA}"
        ;;

    *)
        echo "Unknown target: $TARGET"
        echo "$USAGE"
        exit 1
        ;;
esac

echo ""
echo "Deploy complete: ${TARGET} -> ${REGISTRY}/${TARGET}:${SHA}"
