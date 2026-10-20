"""Unit tests for the Flask application and its configuration loading."""

import pytest

from app import create_app
from config import VALID_ENVIRONMENTS, AppConfig


def make_client(**env):
    app = create_app(env)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.mark.parametrize("environment", VALID_ENVIRONMENTS)
def test_dashboard_shows_name_environment_and_version(environment):
    client = make_client(APP_NAME="Demo App", APP_ENV=environment, APP_VERSION="2.3.4")
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Demo App" in html
    assert environment.upper() in html
    assert "v2.3.4" in html


def test_health_and_ready_endpoints():
    client = make_client(APP_ENV="staging")
    assert client.get("/health").get_json() == {"status": "ok"}
    ready = client.get("/ready").get_json()
    assert ready == {"status": "ready", "environment": "staging"}


def test_api_config_reflects_environment_variables():
    client = make_client(
        APP_ENV="production",
        APP_VERSION="1.0.0",
        LOG_LEVEL="warning",
        DEBUG_MODE="false",
        MAX_CONNECTIONS="200",
        DATABASE_HOST="postgres.prod.svc.cluster.local",
    )
    data = client.get("/api/config").get_json()
    assert data["environment"] == "production"
    assert data["version"] == "1.0.0"
    settings = data["settings"]
    assert settings["LOG_LEVEL"] == "WARNING"
    assert settings["DEBUG_MODE"] is False
    assert settings["MAX_CONNECTIONS"] == 200
    assert settings["DATABASE_HOST"] == "postgres.prod.svc.cluster.local"


def test_secret_key_is_never_exposed():
    client = make_client(APP_ENV="production", SECRET_KEY="super-secret-value-123")
    api_body = client.get("/api/config").get_data(as_text=True)
    page_body = client.get("/").get_data(as_text=True)
    assert "super-secret-value-123" not in api_body
    assert "super-secret-value-123" not in page_body
    assert "kubernetes-secret" in api_body


def test_secret_key_is_generated_when_not_provided():
    first = AppConfig({})
    second = AppConfig({})
    assert first.secret_key_source == "auto-generated"
    assert len(first.secret_key) == 64
    assert first.secret_key != second.secret_key


def test_invalid_environment_falls_back_to_development():
    cfg = AppConfig({"APP_ENV": "qa-sandbox"})
    assert cfg.environment == "development"
    assert cfg.environment_is_valid is False


@pytest.mark.parametrize(
    "environment,theme",
    [("development", "success"), ("testing", "info"), ("staging", "warning"), ("production", "danger")],
)
def test_each_environment_has_distinct_theme(environment, theme):
    assert AppConfig({"APP_ENV": environment}).theme == theme


def test_beta_banner_toggle():
    on = make_client(APP_ENV="development", FEATURE_BETA_BANNER="true").get("/").get_data(as_text=True)
    off = make_client(APP_ENV="production", FEATURE_BETA_BANNER="false").get("/").get_data(as_text=True)
    assert "Beta features are enabled" in on
    assert "Beta features are enabled" not in off


def test_bad_numeric_values_use_defaults():
    cfg = AppConfig({"MAX_CONNECTIONS": "lots", "CACHE_TTL_SECONDS": ""})
    assert cfg.max_connections == 10
    assert cfg.cache_ttl_seconds == 60
