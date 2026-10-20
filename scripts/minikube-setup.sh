#!/usr/bin/env bash
# Start Minikube, build the application image inside it and create the
# four environment namespaces.
#
# Usage: ./scripts/minikube-setup.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"
require_cmd minikube kubectl helm

log "Starting Minikube (skipped if already running)"
if ! minikube status >/dev/null 2>&1; then
  minikube start --cpus=2 --memory=4096 --driver="${MINIKUBE_DRIVER:-docker}"
fi
kubectl cluster-info

log "Building image ${IMAGE_REPO}:${IMAGE_TAG} inside Minikube"
# Builds directly into Minikube's container runtime, so no registry is needed.
minikube image build -t "${IMAGE_REPO}:${IMAGE_TAG}" "${PROJECT_ROOT}"

log "Creating namespaces"
for env in "${ALL_ENVS[@]}"; do
  kubectl create namespace "$(namespace_for "$env")" --dry-run=client -o yaml | kubectl apply -f -
done

log "Done. Next: ./scripts/deploy.sh dev   (or: ./scripts/deploy.sh all)"
