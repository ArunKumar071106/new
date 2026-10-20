"""Tests that verify the environment-specific Helm configuration.

Part 1 (always runs): static checks of the values-*.yaml files with PyYAML.
Part 2 (runs when the `helm` binary is on PATH): renders the chart for each
environment with `helm template` and checks the generated Kubernetes objects.
"""

import os
import re
import shutil
import subprocess

import pytest
import yaml

from conftest import CHART_DIR

ENVIRONMENTS = {
    # file suffix: (expected environment, expected nodePort, minimum replicas)
    "dev": ("development", 30081, 1),
    "test": ("testing", 30082, 1),
    "staging": ("staging", 30083, 2),
    "prod": ("production", 30084, 3),
}

REQUIRED_CHART_FILES = [
    "Chart.yaml",
    "values.yaml",
    "values-dev.yaml",
    "values-test.yaml",
    "values-staging.yaml",
    "values-prod.yaml",
    "values.schema.json",
    "templates/deployment.yaml",
    "templates/service.yaml",
    "templates/configmap.yaml",
]

SECRET_KEY_PATTERN = re.compile(r"(password|passwd|secret_key|token|api_key|private_key)", re.IGNORECASE)


def load_yaml(name):
    with open(os.path.join(CHART_DIR, name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def merged_values(suffix):
    """Shallow+nested merge of values.yaml and values-<suffix>.yaml (like Helm)."""

    def merge(base, override):
        out = dict(base)
        for key, val in override.items():
            if isinstance(val, dict) and isinstance(out.get(key), dict):
                out[key] = merge(out[key], val)
            else:
                out[key] = val
        return out

    return merge(load_yaml("values.yaml"), load_yaml("values-{}.yaml".format(suffix)))


# --------------------------------------------------------------------------
# Part 1: static checks
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", REQUIRED_CHART_FILES)
def test_required_chart_files_exist(path):
    assert os.path.isfile(os.path.join(CHART_DIR, path)), path


def test_chart_metadata():
    chart = load_yaml("Chart.yaml")
    assert chart["apiVersion"] == "v2"
    assert chart["name"] == "multi-env-app"
    assert re.match(r"^\d+\.\d+\.\d+$", chart["version"])
    assert re.match(r"^\d+\.\d+\.\d+$", str(chart["appVersion"]))


@pytest.mark.parametrize("suffix", ENVIRONMENTS)
def test_environment_name_matches_file(suffix):
    expected_env, _, _ = ENVIRONMENTS[suffix]
    assert merged_values(suffix)["environment"] == expected_env


@pytest.mark.parametrize("suffix", ENVIRONMENTS)
def test_replica_policy(suffix):
    _, _, min_replicas = ENVIRONMENTS[suffix]
    assert merged_values(suffix)["replicaCount"] >= min_replicas


@pytest.mark.parametrize("suffix", ENVIRONMENTS)
def test_every_environment_defines_the_same_config_keys(suffix):
    base_keys = set(load_yaml("values.yaml")["config"])
    env_keys = set(load_yaml("values-{}.yaml".format(suffix))["config"])
    assert env_keys == base_keys, "config keys differ from values.yaml: {}".format(env_keys ^ base_keys)


def test_node_ports_are_unique_and_valid():
    ports = [merged_values(s)["service"]["nodePort"] for s in ENVIRONMENTS]
    assert len(set(ports)) == len(ports)
    for suffix, port in zip(ENVIRONMENTS, ports):
        assert port == ENVIRONMENTS[suffix][1]
        assert 30000 <= port <= 32767


def test_production_hardening():
    prod = merged_values("prod")
    assert prod["config"]["DEBUG_MODE"] == "false"
    assert prod["config"]["LOG_LEVEL"] in ("WARNING", "ERROR")
    assert prod["config"]["FEATURE_BETA_BANNER"] == "false"
    assert prod["existingSecret"], "production must load SECRET_KEY from a Kubernetes Secret"
    assert prod["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
    assert prod["resources"]["limits"]["memory"]


def test_staging_matches_production_feature_flags():
    staging, prod = merged_values("staging")["config"], merged_values("prod")["config"]
    assert staging["DEBUG_MODE"] == prod["DEBUG_MODE"]
    assert staging["FEATURE_BETA_BANNER"] == prod["FEATURE_BETA_BANNER"]


def test_development_is_verbose():
    dev = merged_values("dev")["config"]
    assert dev["LOG_LEVEL"] == "DEBUG"
    assert dev["DEBUG_MODE"] == "true"


@pytest.mark.parametrize("name", ["values.yaml"] + ["values-{}.yaml".format(s) for s in ENVIRONMENTS])
def test_no_hardcoded_secrets(name):
    """No secret-looking key may carry a literal value in any values file."""

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, val in node.items():
                yield from walk(val, "{}.{}".format(path, key) if path else str(key))
        else:
            yield path, node

    for path, value in walk(load_yaml(name)):
        leaf = path.split(".")[-1]
        if SECRET_KEY_PATTERN.search(leaf) and value not in ("", None):
            pytest.fail("{}: '{}' looks like a hardcoded secret".format(name, path))


# --------------------------------------------------------------------------
# Part 2: render the chart with Helm
# --------------------------------------------------------------------------

HELM = shutil.which("helm")
needs_helm = pytest.mark.skipif(HELM is None, reason="helm binary not installed")


def helm_template(suffix):
    out = subprocess.run(
        [HELM, "template", "myapp-" + suffix, CHART_DIR, "-f",
         os.path.join(CHART_DIR, "values-{}.yaml".format(suffix)), "--namespace", suffix],
        check=True, capture_output=True, text=True,
    ).stdout
    return {doc["kind"]: doc for doc in yaml.safe_load_all(out) if doc}


@needs_helm
@pytest.mark.parametrize("suffix", ENVIRONMENTS)
def test_helm_lint_strict(suffix):
    result = subprocess.run(
        [HELM, "lint", CHART_DIR, "--strict", "-f", os.path.join(CHART_DIR, "values-{}.yaml".format(suffix))],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@needs_helm
@pytest.mark.parametrize("suffix", ENVIRONMENTS)
def test_rendered_manifests_match_environment(suffix):
    expected_env, node_port, _ = ENVIRONMENTS[suffix]
    values = merged_values(suffix)
    docs = helm_template(suffix)

    assert {"ConfigMap", "Deployment", "Service"} <= set(docs)

    cm = docs["ConfigMap"]["data"]
    assert cm["APP_ENV"] == expected_env
    assert cm["APP_VERSION"] == str(load_yaml("Chart.yaml")["appVersion"])
    for key, val in values["config"].items():
        assert cm[key] == str(val)

    dep = docs["Deployment"]
    assert dep["spec"]["replicas"] == values["replicaCount"]
    assert dep["metadata"]["labels"]["app.kubernetes.io/environment"] == expected_env
    pod = dep["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert container["envFrom"][0]["configMapRef"]["name"] == docs["ConfigMap"]["metadata"]["name"]
    assert container["resources"] == values["resources"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert "checksum/config" in dep["spec"]["template"]["metadata"]["annotations"]

    svc = docs["Service"]
    assert svc["spec"]["ports"][0]["nodePort"] == node_port


@needs_helm
def test_production_mounts_existing_secret():
    container = helm_template("prod")["Deployment"]["spec"]["template"]["spec"]["containers"][0]
    refs = [ref for ref in container["envFrom"] if "secretRef" in ref]
    assert refs and refs[0]["secretRef"]["name"] == merged_values("prod")["existingSecret"]


@needs_helm
def test_config_change_changes_checksum():
    """Changing a config value must roll the pods (new checksum annotation)."""

    def checksum(*extra):
        out = subprocess.run(
            [HELM, "template", "r", CHART_DIR, "-f", os.path.join(CHART_DIR, "values-dev.yaml"), *extra],
            check=True, capture_output=True, text=True,
        ).stdout
        dep = next(d for d in yaml.safe_load_all(out) if d and d["kind"] == "Deployment")
        return dep["spec"]["template"]["metadata"]["annotations"]["checksum/config"]

    assert checksum() != checksum("--set", "config.LOG_LEVEL=INFO")


@needs_helm
@pytest.mark.parametrize(
    "override",
    ["environment=qa", "replicaCount=0", "config.LOG_LEVEL=VERBOSE", "config.SECRET_KEY=abc", "service.nodePort=80"],
)
def test_schema_rejects_invalid_values(override):
    result = subprocess.run([HELM, "lint", CHART_DIR, "--set", override], capture_output=True, text=True)
    assert result.returncode != 0, "schema accepted invalid value: " + override
