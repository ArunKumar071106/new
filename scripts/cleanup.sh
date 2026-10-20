#!/usr/bin/env bash
# Uninstall every release and delete the environment namespaces.
# Usage: ./scripts/cleanup.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"
require_cmd kubectl helm

for env in "${ALL_ENVS[@]}"; do
  ns="$(namespace_for "$env")"; release="$(release_for "$env")"
  helm uninstall "$release" -n "$ns" 2>/dev/null && echo "uninstalled ${release}" || true
  kubectl delete namespace "$ns" --ignore-not-found
done
