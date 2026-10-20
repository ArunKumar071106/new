#!/usr/bin/env bash
# Validate the Helm chart for every environment WITHOUT touching a cluster:
#   1. helm lint --strict (also enforces values.schema.json)
#   2. helm template (render) for each values file
#   3. kubeconform schema validation of the rendered manifests (if installed)
#
# Usage: ./scripts/validate-helm.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"
require_cmd helm

OUT_DIR="${PROJECT_ROOT}/dist/rendered"
mkdir -p "$OUT_DIR"
failures=0

for env in "${ALL_ENVS[@]}"; do
  values="$(values_for "$env")"
  log "[$env] helm lint --strict"
  helm lint "$CHART_DIR" --strict -f "$values" || failures=$((failures + 1))

  log "[$env] helm template"
  out="${OUT_DIR}/${env}.yaml"
  if helm template "$(release_for "$env")" "$CHART_DIR" -f "$values" -n "$(namespace_for "$env")" > "$out"; then
    grep -q "APP_ENV: \"$(app_env_for "$env")\"" "$out" \
      && echo "APP_ENV correctly rendered as $(app_env_for "$env")" \
      || { echo "APP_ENV mismatch in $out"; failures=$((failures + 1)); }
  else
    failures=$((failures + 1))
  fi

  if command -v kubeconform >/dev/null 2>&1; then
    log "[$env] kubeconform"
    kubeconform -strict -summary -kubernetes-version "${KUBERNETES_VERSION:-1.31.0}" "$out" \
      || failures=$((failures + 1))
  else
    echo "kubeconform not installed - skipping Kubernetes schema validation"
  fi
done

log "Rendered manifests written to ${OUT_DIR}"
if [[ $failures -gt 0 ]]; then
  echo "VALIDATION FAILED (${failures} problem(s))" >&2
  exit 1
fi
echo "All environments validated successfully."
