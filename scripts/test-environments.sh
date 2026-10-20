#!/usr/bin/env bash
# Live verification of deployed environments. For each environment it checks:
#   - the Helm release is deployed
#   - all desired replicas are ready
#   - the running app reports the expected environment (via /api/config)
#   - /health returns ok
#   - `helm test` passes
#
# Usage: ./scripts/test-environments.sh [dev|test|staging|prod|all]   (default: all)
set -uo pipefail
source "$(dirname "$0")/common.sh"
require_cmd kubectl helm curl python3

TARGET="${1:-all}"
[[ "$TARGET" == "all" ]] && ENVS=("${ALL_ENVS[@]}") || { require_env "$TARGET"; ENVS=("$TARGET"); }

pass=0; fail=0
check() {  # check <description> <command...>
  local desc="$1"; shift
  if "$@"; then echo "  PASS  $desc"; pass=$((pass + 1)); else echo "  FAIL  $desc"; fail=$((fail + 1)); fi
}

json_field() {  # json_field <python expression on d>
  python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"
}

local_port=18080
for env in "${ENVS[@]}"; do
  ns="$(namespace_for "$env")"; release="$(release_for "$env")"; expected="$(app_env_for "$env")"
  log "Testing environment '${env}' (release ${release}, namespace ${ns})"

  if ! helm status "$release" -n "$ns" >/dev/null 2>&1; then
    echo "  FAIL  release ${release} is not installed"; fail=$((fail + 1)); continue
  fi
  check "helm release status is deployed" \
    bash -c "helm status '$release' -n '$ns' -o json | python3 -c 'import json,sys; sys.exit(json.load(sys.stdin)[\"info\"][\"status\"] != \"deployed\")'"

  deploy="$(kubectl get deploy -n "$ns" -l "app.kubernetes.io/instance=${release}" -o jsonpath='{.items[0].metadata.name}')"
  desired="$(kubectl get deploy "$deploy" -n "$ns" -o jsonpath='{.spec.replicas}')"
  ready="$(kubectl get deploy "$deploy" -n "$ns" -o jsonpath='{.status.readyReplicas}')"
  check "replicas ready (${ready:-0}/${desired})" test "${ready:-0}" = "$desired"

  svc="$(kubectl get svc -n "$ns" -l "app.kubernetes.io/instance=${release}" -o jsonpath='{.items[0].metadata.name}')"
  kubectl port-forward -n "$ns" "svc/${svc}" "${local_port}:80" >/dev/null 2>&1 &
  pf_pid=$!
  for _ in $(seq 1 20); do curl -fs "http://127.0.0.1:${local_port}/health" >/dev/null 2>&1 && break; sleep 0.5; done

  body="$(curl -fs "http://127.0.0.1:${local_port}/api/config" || echo '{}')"
  actual="$(echo "$body" | json_field 'd.get("environment")')"
  check "APP_ENV is '${expected}' (got '${actual}')" test "$actual" = "$expected"
  replicas_cfg="$(echo "$body" | json_field 'd.get("settings",{}).get("REPLICA_COUNT")')"
  check "REPLICA_COUNT in ConfigMap matches deployment (${replicas_cfg})" test "$replicas_cfg" = "$desired"
  check "/health returns ok" bash -c "curl -fs http://127.0.0.1:${local_port}/health | grep -q ok"
  if [[ "$env" == "prod" ]]; then
    debug="$(echo "$body" | json_field 'd["settings"]["DEBUG_MODE"]')"
    check "production DEBUG_MODE is False" test "$debug" = "False"
    src="$(echo "$body" | json_field 'd["settings"]["SECRET_KEY"]')"
    check "production SECRET_KEY comes from a Kubernetes Secret" bash -c "echo '$src' | grep -q kubernetes-secret"
  fi
  kill "$pf_pid" >/dev/null 2>&1; wait "$pf_pid" 2>/dev/null
  local_port=$((local_port + 1))

  check "helm test ${release}" bash -c "helm test '$release' -n '$ns' --timeout 2m >/dev/null"
done

echo
echo "Result: ${pass} passed, ${fail} failed"
[[ $fail -eq 0 ]]
