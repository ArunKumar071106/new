# Evidence for the project report

Files in this folder are produced by `scripts/capture-evidence.sh`, which the workflow
`.github/workflows/capture-evidence.yml` runs on a throw-away kind cluster in GitHub Actions
and commits back to the branch. The project report quotes these files.

| File | Content |
|---|---|
| `00-environment.txt` | Runner, tool versions, node, image size and layers |
| `01-deploy-all.txt` | Output of `scripts/deploy.sh all` |
| `02-*.txt`, `pods-*.json` | Objects of every environment (`kubectl get deploy,svc,cm,pods`), `helm list -A` |
| `03-*.txt` | Production ConfigMap, Deployment description, Helm values |
| `04-logs.txt` | Application logs of dev and prod (effect of `LOG_LEVEL`) |
| `05-live-tests.txt` | Output of `scripts/test-environments.sh all` |
| `06-upgrade-rollback.txt` | `helm upgrade`, `helm history`, `helm rollback` on the dev release |
| `07-atomic-failure.txt` | Upgrade with a non-existent image tag and `--atomic` |
| `08-availability.txt` | Failed requests during rolling updates (three scenarios) |
| `09-missing-secret.txt` | Production installed without its Secret |
| `10-final-state.txt` | `helm list -A` and pods at the end |
| `dashboard-*.png`, `*-api.json` | Screenshots and `/api/config` of the dashboards served by the pods |

To regenerate on your own cluster (Minikube or kind): build or load the image, then run
`./scripts/capture-evidence.sh`. A headless Chrome or Chromium is needed for the screenshots.
