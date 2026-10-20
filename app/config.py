"""Runtime configuration for the Multi-Environment Config Dashboard.

All values are read from environment variables. In Kubernetes these
variables are injected from the Helm-generated ConfigMap (non-sensitive
settings) and, optionally, from a pre-created Kubernetes Secret.
Nothing sensitive is hardcoded here.
"""

import os
import secrets

VALID_ENVIRONMENTS = ("development", "testing", "staging", "production")

# Bootstrap colour used for the environment badge / banner on the dashboard.
ENVIRONMENT_THEMES = {
    "development": "success",
    "testing": "info",
    "staging": "warning",
    "production": "danger",
}

# Keys whose values must never be displayed or returned by the API.
SENSITIVE_KEYS = ("SECRET_KEY",)


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class AppConfig:
    """Snapshot of the application configuration taken from the environment."""

    def __init__(self, environ=None):
        env = os.environ if environ is None else environ

        self.app_name = env.get("APP_NAME", "Multi-Env Config Dashboard")
        raw_env = env.get("APP_ENV", "development").strip().lower()
        self.environment_is_valid = raw_env in VALID_ENVIRONMENTS
        self.environment = raw_env if self.environment_is_valid else "development"
        self.app_version = env.get("APP_VERSION", "1.0.0")

        self.log_level = env.get("LOG_LEVEL", "INFO").upper()
        self.debug = _as_bool(env.get("DEBUG_MODE"), default=False)
        self.feature_beta_banner = _as_bool(env.get("FEATURE_BETA_BANNER"))
        self.max_connections = _as_int(env.get("MAX_CONNECTIONS"), 10)
        self.cache_ttl_seconds = _as_int(env.get("CACHE_TTL_SECONDS"), 60)
        self.database_host = env.get("DATABASE_HOST", "localhost")
        self.api_base_url = env.get("API_BASE_URL", "http://localhost:5000/api")
        self.replica_count = env.get("REPLICA_COUNT", "1")

        # Kubernetes downward-API values (present only inside a pod).
        self.pod_name = env.get("POD_NAME", "local")
        self.pod_namespace = env.get("POD_NAMESPACE", "local")
        self.node_name = env.get("NODE_NAME", "local")
        self.helm_release = env.get("HELM_RELEASE", "not-deployed-with-helm")
        self.chart_version = env.get("HELM_CHART_VERSION", "n/a")

        # Secret key: supplied via a Kubernetes Secret, or generated per
        # process so that no secret is ever committed to source control.
        provided_secret = env.get("SECRET_KEY")
        self.secret_key_source = "kubernetes-secret" if provided_secret else "auto-generated"
        self.secret_key = provided_secret or secrets.token_hex(32)

    @property
    def theme(self):
        return ENVIRONMENT_THEMES[self.environment]

    def public_settings(self):
        """Settings that are safe to show on the dashboard / JSON API."""
        return {
            "APP_NAME": self.app_name,
            "APP_ENV": self.environment,
            "APP_VERSION": self.app_version,
            "LOG_LEVEL": self.log_level,
            "DEBUG_MODE": self.debug,
            "FEATURE_BETA_BANNER": self.feature_beta_banner,
            "MAX_CONNECTIONS": self.max_connections,
            "CACHE_TTL_SECONDS": self.cache_ttl_seconds,
            "DATABASE_HOST": self.database_host,
            "API_BASE_URL": self.api_base_url,
            "REPLICA_COUNT": self.replica_count,
            "SECRET_KEY": "******** ({})".format(self.secret_key_source),
        }

    def runtime_info(self):
        return {
            "POD_NAME": self.pod_name,
            "POD_NAMESPACE": self.pod_namespace,
            "NODE_NAME": self.node_name,
            "HELM_RELEASE": self.helm_release,
            "HELM_CHART_VERSION": self.chart_version,
        }
