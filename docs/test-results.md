# Test Results

Actual output from the test runs made while building this project (20 October 2026).
Two places were used:

- **Development sandbox**: Linux, Python 3.13, Helm 3.16 (built from source), kubeconform 0.6.7, Docker 29.9. No Kubernetes cluster could run there (nested containers are not supported).
- **GitHub Actions** (`.github/workflows/helm-validation.yml`, run #1 on branch `ccr-6fca26d4-n2tv4m`): ubuntu-latest, Python 3.12, Helm v3.16.2, kubeconform v0.6.7, and a **kind** v0.31.0 cluster running Kubernetes v1.35.0 (node image `kindest/node:v1.35.0`). All 4 jobs passed.

## 1. pytest – 62 tests (sandbox; identical result in GitHub Actions: `62 passed in 1.17s`)

```
tests/test_app.py::test_dashboard_shows_name_environment_and_version[development] PASSED
tests/test_app.py::test_dashboard_shows_name_environment_and_version[testing] PASSED
tests/test_app.py::test_dashboard_shows_name_environment_and_version[staging] PASSED
tests/test_app.py::test_dashboard_shows_name_environment_and_version[production] PASSED
tests/test_app.py::test_health_and_ready_endpoints PASSED
tests/test_app.py::test_api_config_reflects_environment_variables PASSED
tests/test_app.py::test_secret_key_is_never_exposed PASSED
tests/test_app.py::test_secret_key_is_generated_when_not_provided PASSED
tests/test_app.py::test_invalid_environment_falls_back_to_development PASSED
tests/test_app.py::test_each_environment_has_distinct_theme[development-success] PASSED
tests/test_app.py::test_each_environment_has_distinct_theme[testing-info] PASSED
tests/test_app.py::test_each_environment_has_distinct_theme[staging-warning] PASSED
tests/test_app.py::test_each_environment_has_distinct_theme[production-danger] PASSED
tests/test_app.py::test_beta_banner_toggle PASSED
tests/test_app.py::test_bad_numeric_values_use_defaults PASSED
tests/test_helm_config.py::test_required_chart_files_exist[Chart.yaml] PASSED
tests/test_helm_config.py::test_required_chart_files_exist[values.yaml] PASSED
tests/test_helm_config.py::test_required_chart_files_exist[values-dev.yaml] PASSED
tests/test_helm_config.py::test_required_chart_files_exist[values-test.yaml] PASSED
tests/test_helm_config.py::test_required_chart_files_exist[values-staging.yaml] PASSED
tests/test_helm_config.py::test_required_chart_files_exist[values-prod.yaml] PASSED
tests/test_helm_config.py::test_required_chart_files_exist[values.schema.json] PASSED
tests/test_helm_config.py::test_required_chart_files_exist[templates/deployment.yaml] PASSED
tests/test_helm_config.py::test_required_chart_files_exist[templates/service.yaml] PASSED
tests/test_helm_config.py::test_required_chart_files_exist[templates/configmap.yaml] PASSED
tests/test_helm_config.py::test_chart_metadata PASSED
tests/test_helm_config.py::test_environment_name_matches_file[dev] PASSED
tests/test_helm_config.py::test_environment_name_matches_file[test] PASSED
tests/test_helm_config.py::test_environment_name_matches_file[staging] PASSED
tests/test_helm_config.py::test_environment_name_matches_file[prod] PASSED
tests/test_helm_config.py::test_replica_policy[dev] PASSED
tests/test_helm_config.py::test_replica_policy[test] PASSED
tests/test_helm_config.py::test_replica_policy[staging] PASSED
tests/test_helm_config.py::test_replica_policy[prod] PASSED
tests/test_helm_config.py::test_every_environment_defines_the_same_config_keys[dev] PASSED
tests/test_helm_config.py::test_every_environment_defines_the_same_config_keys[test] PASSED
tests/test_helm_config.py::test_every_environment_defines_the_same_config_keys[staging] PASSED
tests/test_helm_config.py::test_every_environment_defines_the_same_config_keys[prod] PASSED
tests/test_helm_config.py::test_node_ports_are_unique_and_valid PASSED
tests/test_helm_config.py::test_production_hardening PASSED
tests/test_helm_config.py::test_staging_matches_production_feature_flags PASSED
tests/test_helm_config.py::test_development_is_verbose PASSED
tests/test_helm_config.py::test_no_hardcoded_secrets[values.yaml] PASSED
tests/test_helm_config.py::test_no_hardcoded_secrets[values-dev.yaml] PASSED
tests/test_helm_config.py::test_no_hardcoded_secrets[values-test.yaml] PASSED
tests/test_helm_config.py::test_no_hardcoded_secrets[values-staging.yaml] PASSED
tests/test_helm_config.py::test_no_hardcoded_secrets[values-prod.yaml] PASSED
tests/test_helm_config.py::test_helm_lint_strict[dev] PASSED
tests/test_helm_config.py::test_helm_lint_strict[test] PASSED
tests/test_helm_config.py::test_helm_lint_strict[staging] PASSED
tests/test_helm_config.py::test_helm_lint_strict[prod] PASSED
tests/test_helm_config.py::test_rendered_manifests_match_environment[dev] PASSED
tests/test_helm_config.py::test_rendered_manifests_match_environment[test] PASSED
tests/test_helm_config.py::test_rendered_manifests_match_environment[staging] PASSED
tests/test_helm_config.py::test_rendered_manifests_match_environment[prod] PASSED
tests/test_helm_config.py::test_production_mounts_existing_secret PASSED
tests/test_helm_config.py::test_config_change_changes_checksum PASSED
tests/test_helm_config.py::test_schema_rejects_invalid_values[environment=qa] PASSED
tests/test_helm_config.py::test_schema_rejects_invalid_values[replicaCount=0] PASSED
tests/test_helm_config.py::test_schema_rejects_invalid_values[config.LOG_LEVEL=VERBOSE] PASSED
tests/test_helm_config.py::test_schema_rejects_invalid_values[config.SECRET_KEY=abc] PASSED
tests/test_helm_config.py::test_schema_rejects_invalid_values[service.nodePort=80] PASSED
============================== 62 passed in 1.74s ==============================
```

## 2. Helm chart validation – `./scripts/validate-helm.sh` (sandbox; also passed in GitHub Actions)

```
==> [dev] helm lint --strict
==> Linting helm/multi-env-app
[INFO] Chart.yaml: icon is recommended
1 chart(s) linted, 0 chart(s) failed
==> [dev] helm template
APP_ENV correctly rendered as development
==> [dev] kubeconform
Summary: 4 resources found in 1 file - Valid: 4, Invalid: 0, Errors: 0, Skipped: 0
==> [test] helm lint --strict
==> Linting helm/multi-env-app
[INFO] Chart.yaml: icon is recommended
1 chart(s) linted, 0 chart(s) failed
==> [test] helm template
APP_ENV correctly rendered as testing
==> [test] kubeconform
Summary: 4 resources found in 1 file - Valid: 4, Invalid: 0, Errors: 0, Skipped: 0
==> [staging] helm lint --strict
==> Linting helm/multi-env-app
[INFO] Chart.yaml: icon is recommended
1 chart(s) linted, 0 chart(s) failed
==> [staging] helm template
APP_ENV correctly rendered as staging
==> [staging] kubeconform
Summary: 4 resources found in 1 file - Valid: 4, Invalid: 0, Errors: 0, Skipped: 0
==> [prod] helm lint --strict
==> Linting helm/multi-env-app
[INFO] Chart.yaml: icon is recommended
1 chart(s) linted, 0 chart(s) failed
==> [prod] helm template
APP_ENV correctly rendered as production
==> [prod] kubeconform
Summary: 4 resources found in 1 file - Valid: 4, Invalid: 0, Errors: 0, Skipped: 0
==> Rendered manifests written to dist/rendered
All environments validated successfully.
```

The `[INFO] icon is recommended` line is informational only; `--strict` lint still passes.

## 3. Docker image (sandbox)

```
$ docker build -t multi-env-app:1.0.0 .            -> success (image 188 MB on disk, 45.5 MB content)
$ docker run -d -p 5055:5000 -e APP_ENV=staging -e SECRET_KEY=... multi-env-app:1.0.0
$ curl localhost:5055/health                       -> {"status":"ok"}
$ curl localhost:5055/api/config                   -> {"environment":"staging", ..., "SECRET_KEY":"******** (kubernetes-secret)", "version":"1.0.0"}
$ docker exec envtest id                           -> uid=10001(appuser) gid=10001(appuser)
$ docker inspect --format '{{.State.Health.Status}}' -> healthy
```

Note: in the sandbox only, the `python:3.12-slim` base image was pulled from a registry mirror and given the sandbox's TLS certificate so `pip` could reach PyPI. The project's `Dockerfile` was not changed; GitHub Actions built it unmodified.

## 4. Kubernetes deployment on kind (GitHub Actions, job "Deploy all environments to a kind cluster")

`./scripts/deploy.sh all` installed all four releases (`--atomic --wait`):

```
deployment.apps/myapp-staging-multi-env-app   2/2     2            2
service/myapp-staging-multi-env-app   NodePort   10.96.48.171   <none>   80:30083/TCP
Creating Secret multi-env-app-secrets in prod with a random SECRET_KEY
secret/multi-env-app-secrets created
deployment.apps/myapp-prod-multi-env-app   3/3     3            3
service/myapp-prod-multi-env-app   NodePort   10.96.72.105   <none>   80:30084/TCP
```

`./scripts/test-environments.sh all`:

```
==> Testing environment 'dev' (release myapp-dev, namespace dev)
  PASS  helm release status is deployed
  PASS  replicas ready (1/1)
  PASS  APP_ENV is 'development' (got 'development')
  PASS  REPLICA_COUNT in ConfigMap matches deployment (1)
  PASS  /health returns ok
  PASS  helm test myapp-dev
==> Testing environment 'test' (release myapp-test, namespace test)
  PASS  helm release status is deployed
  PASS  replicas ready (1/1)
  PASS  APP_ENV is 'testing' (got 'testing')
  PASS  REPLICA_COUNT in ConfigMap matches deployment (1)
  PASS  /health returns ok
  PASS  helm test myapp-test
==> Testing environment 'staging' (release myapp-staging, namespace staging)
  PASS  helm release status is deployed
  PASS  replicas ready (2/2)
  PASS  APP_ENV is 'staging' (got 'staging')
  PASS  REPLICA_COUNT in ConfigMap matches deployment (2)
  PASS  /health returns ok
  PASS  helm test myapp-staging
==> Testing environment 'prod' (release myapp-prod, namespace prod)
  PASS  helm release status is deployed
  PASS  replicas ready (3/3)
  PASS  APP_ENV is 'production' (got 'production')
  PASS  REPLICA_COUNT in ConfigMap matches deployment (3)
  PASS  /health returns ok
  PASS  production DEBUG_MODE is False
  PASS  production SECRET_KEY comes from a Kubernetes Secret
  PASS  helm test myapp-prod

Result: 26 passed, 0 failed
```

`./scripts/upgrade-rollback-demo.sh dev`:

```
==> Current version: 1.0.0
==> Upgrading myapp-dev to APP_VERSION 1.1.0 and LOG_LEVEL=INFO
Release "myapp-dev" has been upgraded. Happy Helming!
Version after upgrade: 1.1.0
==> Rolling back to revision 1
Rollback was a success! Happy Helming!
Version after rollback: 1.0.0
==> Release history after rollback
REVISION  STATUS      CHART                APP VERSION  DESCRIPTION
1         superseded  multi-env-app-1.0.0  1.0.0        Install complete
2         superseded  multi-env-app-1.0.0  1.0.0        Upgrade complete
3         deployed    multi-env-app-1.0.0  1.0.0        Rollback to 1
```

Final cluster state:

```
NAME           NAMESPACE  REVISION  STATUS    CHART
myapp-dev      dev        3         deployed  multi-env-app-1.0.0
myapp-prod     prod       1         deployed  multi-env-app-1.0.0
myapp-staging  staging    1         deployed  multi-env-app-1.0.0
myapp-test     test       1         deployed  multi-env-app-1.0.0
```

## 5. Not tested

| Item | Reason |
|---|---|
| Minikube (`minikube start`, `minikube image build`, `minikube service`, `scripts/minikube-setup.sh`) | Not available in the sandbox. The same chart and scripts were tested on kind instead, which is also a conformant Kubernetes cluster. |
| Windows / macOS, PowerShell command variants | All runs were on Linux. |
| Dashboard in a browser on a real pod | Screenshots in `docs/screenshots/` were taken from Docker containers started with each environment's settings, so the runtime panel shows `local` instead of pod names. |
| `scripts/cleanup.sh` | Not executed (the CI cluster is deleted automatically). |
