# Architecture and Design

![Architecture](architecture.png)

## 1. Components

| # | Component | Files | Role |
|---|---|---|---|
| 1 | Flask application | `app/app.py`, `app/config.py`, `app/templates/index.html`, `app/static/css/style.css` | Reads all settings from environment variables and shows them on a Bootstrap dashboard and a JSON API. The code is the same in every environment. |
| 2 | Container image | `Dockerfile`, `.dockerignore` | Packages the app with gunicorn on `python:3.12-slim` and runs it as non-root user 10001. One image is promoted to all environments. |
| 3 | Helm chart | `helm/multi-env-app/` | Templates for ConfigMap, Deployment, Service and a test pod. `values.yaml` holds shared defaults. |
| 4 | Environment values | `values-dev.yaml`, `values-test.yaml`, `values-staging.yaml`, `values-prod.yaml` | Only the settings that differ per environment. |
| 5 | Validation rules | `values.schema.json` | Enforced by Helm on `lint`, `template`, `install` and `upgrade`. |
| 6 | Automation scripts | `scripts/*.sh` | Repeatable setup, deploy, validate, test, upgrade/rollback and cleanup. |
| 7 | Tests | `tests/*.py`, `templates/tests/test-connection.yaml` | Unit, configuration, rendering and in-cluster tests. |
| 8 | CI pipeline | `.github/workflows/helm-validation.yml` | Runs all checks and a full kind deployment on every push. |

## 2. How configuration flows into the application

```
values.yaml  ─┐
              ├─► Helm merge ─► templates/configmap.yaml ─► ConfigMap ─┐
values-<env> ─┘                                                        │ envFrom
                                                                       ▼
Kubernetes Secret (prod only, created at deploy time) ──envFrom──► Pod env vars ─► config.AppConfig ─► dashboard / API
                                                                       ▲
Downward API (pod name, namespace, node) ────────────────env─────────────┘
```

1. Helm merges `values.yaml` with the selected `values-<env>.yaml` (later files and `--set` win).
2. `configmap.yaml` writes `APP_NAME`, `APP_ENV`, `APP_VERSION`, `REPLICA_COUNT`, `HELM_RELEASE`, `HELM_CHART_VERSION` and every key under `config:` into a ConfigMap.
3. `deployment.yaml` loads the ConfigMap (and the Secret, when `existingSecret` is set) into the container with `envFrom`, and adds pod name/namespace/node from the Downward API.
4. `app/config.py` reads the variables, validates `APP_ENV`, converts types and hides `SECRET_KEY`.
5. The Deployment's pod template has a `checksum/config` annotation (SHA-256 of the rendered ConfigMap). Any configuration change changes the checksum, so Kubernetes performs a rolling restart and pods pick up the new values.

## 3. Isolation between environments

| Mechanism | Effect |
|---|---|
| One namespace per environment (`dev`, `test`, `staging`, `prod`) | Objects with the same name cannot clash; access can be limited per namespace. |
| One Helm release per environment (`myapp-<env>`) | Independent revision history, upgrade and rollback. |
| Release-based names (`myapp-prod-multi-env-app`) and labels (`app.kubernetes.io/instance`, `app.kubernetes.io/environment`) | Selectors only match pods of their own release. |
| Unique NodePorts (30081–30084) | Every environment has its own stable URL on Minikube. |

## 4. Release lifecycle

```
 helm upgrade --install (rev 1) ──► helm upgrade --set ... (rev 2) ──► helm rollback <rel> 1 (rev 3 = copy of rev 1)
          │                                   │                                    │
          └── stored as Secret sh.helm.release.v1.<rel>.v<N> in the namespace ─────┘
```

- `--atomic` rolls back automatically if an upgrade does not become ready within the timeout.
- `--wait` waits until all pods pass their readiness probe (`/ready`).
- Production uses `maxSurge: 1, maxUnavailable: 0`, so a new pod must be ready before an old one is removed.

## 5. Validation layers

| Stage | Tool | Example of a mistake it catches |
|---|---|---|
| Before rendering | `values.schema.json` (via `helm lint`) | `environment: qa`, `replicaCount: 0`, `LOG_LEVEL: VERBOSE`, `SECRET_KEY` placed in `config:` |
| Policy tests | `tests/test_helm_config.py` | prod with `DEBUG_MODE: "true"`, staging feature flags different from prod, a missing config key in one environment, duplicate NodePorts, a hard-coded password |
| After rendering | `helm template` + kubeconform | invalid Kubernetes fields or types in templates |
| After deployment | `helm test`, `scripts/test-environments.sh` | the running pod reports the wrong environment, replicas not ready, Secret not mounted |

## 6. Security choices

- No secrets in Git; Secret values are generated at deploy time and only referenced by name in the chart.
- The container runs as non-root (`runAsNonRoot`, UID 10001), with `allowPrivilegeEscalation: false` and all Linux capabilities dropped.
- CPU and memory requests and limits are set for every environment.
- The API and dashboard mask `SECRET_KEY`.
