#!/usr/bin/env bash
# Shared settings for all scripts. Source this file; do not execute it.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART_DIR="${PROJECT_ROOT}/helm/multi-env-app"
IMAGE_REPO="${IMAGE_REPO:-multi-env-app}"
IMAGE_TAG="${IMAGE_TAG:-$(awk '/^appVersion:/ {gsub(/"/, "", $2); print $2}' "${CHART_DIR}/Chart.yaml")}"
RELEASE_PREFIX="${RELEASE_PREFIX:-myapp}"
SECRET_NAME="multi-env-app-secrets"
ALL_ENVS=(dev test staging prod)

# Environment short name -> namespace / values file / expected APP_ENV / NodePort.
namespace_for()  { echo "$1"; }
values_for()     { echo "${CHART_DIR}/values-$1.yaml"; }
release_for()    { echo "${RELEASE_PREFIX}-$1"; }
app_env_for() {
  case "$1" in
    dev) echo development ;; test) echo testing ;;
    staging) echo staging ;; prod) echo production ;;
    *) return 1 ;;
  esac
}
node_port_for() {
  case "$1" in
    dev) echo 30081 ;; test) echo 30082 ;; staging) echo 30083 ;; prod) echo 30084 ;;
    *) return 1 ;;
  esac
}

require_env() {
  if ! app_env_for "${1:-}" >/dev/null; then
    echo "ERROR: environment must be one of: ${ALL_ENVS[*]} (got '${1:-}')" >&2
    exit 1
  fi
}

require_cmd() {
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: '$cmd' is not installed or not on PATH" >&2; exit 1; }
  done
}

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
