#!/usr/bin/env bash
# Demonstrates the Helm release lifecycle on one environment:
#   install (v1.0.0) -> upgrade (v1.1.0) -> history -> rollback -> history
#
# Usage: ./scripts/upgrade-rollback-demo.sh [dev|test|staging|prod]   (default: dev)
set -euo pipefail
source "$(dirname "$0")/common.sh"
require_cmd kubectl helm

ENV_NAME="${1:-dev}"
require_env "$ENV_NAME"
NS="$(namespace_for "$ENV_NAME")"
RELEASE="$(release_for "$ENV_NAME")"
VALUES="$(values_for "$ENV_NAME")"
NEW_VERSION="${NEW_VERSION:-1.1.0}"

show_version() {
  kubectl get configmap -n "$NS" -l "app.kubernetes.io/instance=${RELEASE}" \
    -o jsonpath='{.items[0].data.APP_VERSION}'
}

if ! helm status "$RELEASE" -n "$NS" >/dev/null 2>&1; then
  log "Release not found - installing first"
  "$(dirname "$0")/deploy.sh" "$ENV_NAME"
fi

ORIGINAL="$(show_version)"
log "Current version: ${ORIGINAL}"

log "Upgrading ${RELEASE} to APP_VERSION ${NEW_VERSION} and LOG_LEVEL=INFO"
# --reuse-values is NOT used on purpose: the values file is always the source of truth.
helm upgrade "$RELEASE" "$CHART_DIR" -n "$NS" -f "$VALUES" \
  --set app.version="${NEW_VERSION}" --set config.LOG_LEVEL=INFO \
  --atomic --wait --timeout 5m
UPGRADED="$(show_version)"
echo "Version after upgrade: ${UPGRADED}"
[[ "$UPGRADED" == "$NEW_VERSION" ]] || { echo "ERROR: upgrade did not apply" >&2; exit 1; }

log "Release history"
helm history "$RELEASE" -n "$NS"

PREVIOUS="$(helm history "$RELEASE" -n "$NS" -o json | python3 -c 'import json,sys; h=json.load(sys.stdin); print(h[-2]["revision"])')"
log "Rolling back to revision ${PREVIOUS}"
helm rollback "$RELEASE" "$PREVIOUS" -n "$NS" --wait --timeout 5m
RESTORED="$(show_version)"
echo "Version after rollback: ${RESTORED}"
[[ "$RESTORED" == "$ORIGINAL" ]] || { echo "ERROR: rollback did not restore ${ORIGINAL}" >&2; exit 1; }

log "Release history after rollback"
helm history "$RELEASE" -n "$NS"
