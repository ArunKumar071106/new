#!/usr/bin/env bash
# Install or upgrade the chart for one environment (or all of them).
#
# Usage: ./scripts/deploy.sh <dev|test|staging|prod|all> [extra helm args...]
# Example: ./scripts/deploy.sh staging --set replicaCount=3
set -euo pipefail
source "$(dirname "$0")/common.sh"
require_cmd kubectl helm

TARGET="${1:-}"
shift || true

ensure_prod_secret() {
  local ns="$1"
  if ! kubectl get secret "${SECRET_NAME}" -n "$ns" >/dev/null 2>&1; then
    log "Creating Secret ${SECRET_NAME} in ${ns} with a random SECRET_KEY"
    # Generated at deploy time - never stored in Git.
    local key
    key="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    kubectl create secret generic "${SECRET_NAME}" -n "$ns" --from-literal=SECRET_KEY="${key}"
  fi
}

deploy_one() {
  local env="$1"; shift
  require_env "$env"
  local ns release values
  ns="$(namespace_for "$env")"
  release="$(release_for "$env")"
  values="$(values_for "$env")"

  log "Deploying ${release} to namespace ${ns} using $(basename "$values")"
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  [[ "$env" == "prod" ]] && ensure_prod_secret "$ns"

  helm upgrade --install "$release" "$CHART_DIR" \
    --namespace "$ns" \
    -f "$values" \
    --atomic --wait --timeout 5m \
    "$@"

  kubectl get deploy,svc,configmap,pods -n "$ns" -l "app.kubernetes.io/instance=${release}"
}

if [[ "$TARGET" == "all" ]]; then
  for env in "${ALL_ENVS[@]}"; do deploy_one "$env" "$@"; done
else
  deploy_one "$TARGET" "$@"
fi
