#!/usr/bin/env bash
# Run all four environments side by side with plain Docker (no Kubernetes).
# Each container gets the same settings Helm would put in its ConfigMap,
# read from values.yaml + values-<env>.yaml. Useful as a quick local demo
# or as a fallback when Minikube is not available.
#
# Usage: ./scripts/docker-demo.sh up     -> http://localhost:8081 (dev) ... 8084 (prod)
#        ./scripts/docker-demo.sh down
set -euo pipefail
source "$(dirname "$0")/common.sh"
require_cmd docker python3

ACTION="${1:-up}"

host_port_for() {
  case "$1" in dev) echo 8081 ;; test) echo 8082 ;; staging) echo 8083 ;; prod) echo 8084 ;; esac
}

# Print the merged settings of one environment as KEY=VALUE lines (env-file format).
env_file_for() {
  python3 - "$CHART_DIR" "$1" "$IMAGE_TAG" <<'PY'
import sys, yaml
chart, env, tag = sys.argv[1:]

def merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out

with open(f"{chart}/values.yaml") as f:
    base = yaml.safe_load(f)
with open(f"{chart}/values-{env}.yaml") as f:
    v = merge(base, yaml.safe_load(f))
print(f"APP_NAME={v['app']['name']}")
print(f"APP_ENV={v['environment']}")
print(f"APP_VERSION={v['app'].get('version') or v['image'].get('tag') or tag}")
print(f"REPLICA_COUNT={v['replicaCount']}")
for key, value in v["config"].items():
    print(f"{key}={value}")
PY
}

case "$ACTION" in
  up)
    for env in "${ALL_ENVS[@]}"; do
      name="multi-env-${env}"
      docker rm -f "$name" >/dev/null 2>&1 || true
      env_file="$(mktemp)"
      env_file_for "$env" > "$env_file"
      docker run -d --name "$name" -p "$(host_port_for "$env"):5000" \
        --env-file "$env_file" "${IMAGE_REPO}:${IMAGE_TAG}" >/dev/null
      rm -f "$env_file"
      echo "${env}: http://localhost:$(host_port_for "$env")"
    done
    ;;
  down)
    for env in "${ALL_ENVS[@]}"; do docker rm -f "multi-env-${env}" >/dev/null 2>&1 || true; done
    echo "stopped"
    ;;
  *)
    echo "Usage: $0 up|down" >&2; exit 1 ;;
esac
