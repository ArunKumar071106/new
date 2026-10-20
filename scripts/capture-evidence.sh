#!/usr/bin/env bash
# Records the evidence quoted in the project report from a running cluster:
# command output (docs/evidence/*.txt, *.json) and dashboard screenshots (*.png).
#
# It deploys all four environments, takes a screenshot of each dashboard,
# upgrades and rolls back the dev release, forces two failures on purpose
# (a bad image tag with --atomic, and production without its Secret) and
# measures how many requests fail while a release is being updated.
#
# Prerequisites: a cluster in the current kubectl context whose nodes already
# have the images multi-env-app:<appVersion> and busybox:1.36, plus helm,
# kubectl, curl, python3 and a headless Chrome or Chromium.
#
# Usage: ./scripts/capture-evidence.sh [output-dir]      (default: docs/evidence)
set -uo pipefail
source "$(dirname "$0")/common.sh"
require_cmd kubectl helm curl python3

OUT="${1:-${PROJECT_ROOT}/docs/evidence}"
BROWSER="${BROWSER:-$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)}"
PROBE_SECONDS="${PROBE_SECONDS:-60}"
CHART="./helm/multi-env-app"

mkdir -p "$OUT"
rm -f "$OUT"/*.txt "$OUT"/*.png "$OUT"/*.json 2>/dev/null
cd "$PROJECT_ROOT"

strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }

# capture <file> <command>: append "$ command" and its output to a text file.
capture() {
  local file="$1"; shift
  { printf '$ %s\n' "$*"; bash -c "$*" 2>&1 | strip_ansi; echo; } >> "${OUT}/${file}"
}

# shoot <name> <namespace> <release> <local-port>: screenshot the dashboard and
# save /api/config next to it. A fresh port-forward is used every time.
shoot() {
  local name="$1" ns="$2" release="$3" port="$4" svc pf
  svc="$(kubectl get svc -n "$ns" -l "app.kubernetes.io/instance=${release}" -o jsonpath='{.items[0].metadata.name}')"
  kubectl port-forward -n "$ns" "svc/${svc}" "${port}:80" >/dev/null 2>&1 &
  pf=$!
  for _ in $(seq 1 40); do curl -fs "http://127.0.0.1:${port}/health" >/dev/null 2>&1 && break; sleep 0.5; done
  curl -s "http://127.0.0.1:${port}/api/config" > "${OUT}/${name}-api.json"
  if [[ -n "$BROWSER" ]]; then
    "$BROWSER" --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
      --force-device-scale-factor=1.5 --window-size=1440,1010 --virtual-time-budget=10000 \
      --screenshot="${OUT}/${name}.png" "http://127.0.0.1:${port}/" >/dev/null 2>&1
  else
    echo "no headless browser found: screenshot ${name} skipped" >&2
  fi
  kill "$pf" 2>/dev/null; wait "$pf" 2>/dev/null
}

section() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
section "Environment"
capture 00-environment.txt 'uname -srm'
capture 00-environment.txt "lscpu | grep 'Model name'"
capture 00-environment.txt 'nproc'
capture 00-environment.txt 'free -h | sed -n 1,2p'
capture 00-environment.txt 'docker --version'
capture 00-environment.txt 'kind version'
capture 00-environment.txt 'kubectl version'
capture 00-environment.txt 'helm version --short'
capture 00-environment.txt 'kubectl get nodes -o wide'
[[ -n "$BROWSER" ]] && capture 00-environment.txt "\"$BROWSER\" --version"
capture 00-environment.txt 'docker image ls multi-env-app'
capture 00-environment.txt 'docker history multi-env-app:1.0.0'

# ---------------------------------------------------------------------------
section "Deploy all environments"
start=$(date +%s)
./scripts/deploy.sh all 2>&1 | tee "${OUT}/.deploy.raw"
end=$(date +%s)
{ strip_ansi < "${OUT}/.deploy.raw"; echo "deploy.sh all finished in $((end - start)) s"; } > "${OUT}/01-deploy-all.txt"
rm -f "${OUT}/.deploy.raw"

section "Cluster state"
capture 02-cluster-state.txt 'kubectl get namespaces'
capture 02-cluster-state.txt 'helm list -A'
for env in "${ALL_ENVS[@]}"; do
  capture "02-resources-${env}.txt" "kubectl get deploy,svc,cm,pods -n ${env} -o wide"
  kubectl get pods -n "$env" -o json > "${OUT}/pods-${env}.json"
done
capture 03-prod-details.txt 'kubectl get secret -n prod'
capture 03-prod-details.txt 'kubectl get configmap myapp-prod-multi-env-app-config -n prod -o yaml'
capture 03-prod-details.txt 'kubectl describe deployment myapp-prod-multi-env-app -n prod'
capture 03-prod-details.txt 'helm get values myapp-prod -n prod'
capture 03-dev-values.txt 'helm get values myapp-dev -n dev --all'
capture 04-logs.txt 'kubectl logs -n dev deploy/myapp-dev-multi-env-app --tail=12'
capture 04-logs.txt 'kubectl logs -n prod deploy/myapp-prod-multi-env-app --tail=12'

section "Live environment tests"
./scripts/test-environments.sh all 2>&1 | strip_ansi > "${OUT}/05-live-tests.txt"

section "Dashboard screenshots"
shoot dashboard-dev     dev     myapp-dev     18081
shoot dashboard-test    test    myapp-test    18082
shoot dashboard-staging staging myapp-staging 18083
shoot dashboard-prod    prod    myapp-prod    18084

# ---------------------------------------------------------------------------
section "Upgrade and rollback of the dev release"
capture 06-upgrade-rollback.txt 'helm history myapp-dev -n dev'
capture 06-upgrade-rollback.txt "helm upgrade myapp-dev ${CHART} -n dev -f helm/multi-env-app/values-dev.yaml --set app.version=1.1.0 --set config.LOG_LEVEL=INFO --atomic --wait --timeout 5m | sed -n 1,8p"
capture 06-upgrade-rollback.txt 'helm history myapp-dev -n dev'
capture 06-upgrade-rollback.txt 'kubectl get pods -n dev'
capture 06-upgrade-rollback.txt 'helm get values myapp-dev -n dev'
shoot dashboard-dev-upgraded dev myapp-dev 18085
capture 06-upgrade-rollback.txt 'helm rollback myapp-dev 1 -n dev --wait --timeout 5m'
capture 06-upgrade-rollback.txt 'helm history myapp-dev -n dev'
shoot dashboard-dev-rolledback dev myapp-dev 18086

# ---------------------------------------------------------------------------
section "Failure 1: bad image tag with --atomic"
capture 07-atomic-failure.txt 'helm history myapp-test -n test'
{
  printf '$ helm upgrade myapp-test %s -n test -f helm/multi-env-app/values-test.yaml --set image.tag=9.9.9 --atomic --wait --timeout 60s\n' "$CHART"
  helm upgrade myapp-test "$CHART" -n test -f helm/multi-env-app/values-test.yaml \
    --set image.tag=9.9.9 --atomic --wait --timeout 60s 2>&1 | strip_ansi
  echo "exit status: ${PIPESTATUS[0]}"; echo
} > "${OUT}/.atomic.raw" &
atomic_pid=$!
sleep 35
capture 07-atomic-failure.txt 'kubectl get pods -n test'
capture 07-atomic-failure.txt "kubectl get events -n test --sort-by=.lastTimestamp | tail -6"
wait "$atomic_pid"
cat "${OUT}/.atomic.raw" >> "${OUT}/07-atomic-failure.txt"; rm -f "${OUT}/.atomic.raw"
capture 07-atomic-failure.txt 'helm history myapp-test -n test'
capture 07-atomic-failure.txt 'kubectl get pods -n test'

section "Failure 2: production without its Secret"
kubectl create namespace demo >/dev/null 2>&1
{
  # NodePorts are unique per cluster, so the demo release must not reuse 30084.
  printf '$ helm install demo-prod %s -n demo -f helm/multi-env-app/values-prod.yaml --set service.nodePort=30089 --wait --timeout 40s\n' "$CHART"
  helm install demo-prod "$CHART" -n demo -f helm/multi-env-app/values-prod.yaml --set service.nodePort=30089 \
    --wait --timeout 40s 2>&1 | strip_ansi
  echo
} > "${OUT}/09-missing-secret.txt"
capture 09-missing-secret.txt 'kubectl get pods -n demo'
capture 09-missing-secret.txt "kubectl get events -n demo --sort-by=.lastTimestamp | grep -i secret | tail -3"
helm uninstall demo-prod -n demo >/dev/null 2>&1
kubectl delete namespace demo --wait=false >/dev/null 2>&1

# ---------------------------------------------------------------------------
# Availability during a rolling update: a busybox pod requests /ready about ten
# times a second while the release is changed; every failed request is logged.
read -r -d '' PROBE_SCRIPT <<'EOF'
start=$(date +%s); n=0; f=0
while [ $(( $(date +%s) - start )) -lt __DURATION__ ]; do
  n=$((n+1))
  if ! wget -q -T 2 -O /dev/null http://__SERVICE__/ready; then
    f=$((f+1)); echo "t=$(( $(date +%s) - start ))s request $n failed"
  fi
  sleep 0.1
done
echo "requests=$n failed=$f"
EOF

# measure_rollout <title> <namespace> <release> <helm upgrade options...>
measure_rollout() {
  local title="$1" ns="$2" release="$3"; shift 3
  local svc="${release}-multi-env-app" script t0 t1
  script="${PROBE_SCRIPT//__DURATION__/$PROBE_SECONDS}"; script="${script//__SERVICE__/$svc}"
  kubectl delete pod probe -n "$ns" --ignore-not-found >/dev/null 2>&1
  kubectl run probe -n "$ns" --image=busybox:1.36 --image-pull-policy=IfNotPresent --restart=Never \
    --command -- sh -c "$script" >/dev/null
  kubectl wait --for=condition=Ready pod/probe -n "$ns" --timeout=60s >/dev/null 2>&1
  sleep 8
  t0=$(date +%s)
  helm upgrade "$release" "$CHART" -n "$ns" -f "helm/multi-env-app/values-${ns}.yaml" "$@" --wait --timeout 3m >/dev/null 2>&1
  t1=$(date +%s)
  kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/probe -n "$ns" --timeout=$((PROBE_SECONDS + 90)) >/dev/null 2>&1
  {
    echo "### ${title}"
    printf '$ helm upgrade %s %s -n %s -f helm/multi-env-app/values-%s.yaml %s --wait\n' "$release" "$CHART" "$ns" "$ns" "$*"
    echo "rollout finished in $((t1 - t0)) s"
    echo "probe output:"
    kubectl logs probe -n "$ns" 2>&1
    echo
  } >> "${OUT}/08-availability.txt"
  kubectl delete pod probe -n "$ns" --ignore-not-found >/dev/null 2>&1
}

section "Availability during rolling updates"
measure_rollout "A: staging (2 replicas), chart strategy maxSurge=1 maxUnavailable=0" staging myapp-staging \
  --set-string config.CACHE_TTL_SECONDS=130
measure_rollout "B: test (1 replica), chart strategy maxSurge=1 maxUnavailable=0" test myapp-test \
  --set-string config.CACHE_TTL_SECONDS=31
measure_rollout "C: test (1 replica), alternative strategy maxSurge=0 maxUnavailable=1" test myapp-test \
  --set-string config.CACHE_TTL_SECONDS=32 --set strategy.rollingUpdate.maxSurge=0 --set strategy.rollingUpdate.maxUnavailable=1

# ---------------------------------------------------------------------------
section "Final state"
capture 10-final-state.txt 'helm list -A'
capture 10-final-state.txt 'kubectl get pods -A -l app.kubernetes.io/name=multi-env-app'
echo "evidence written to ${OUT}"
