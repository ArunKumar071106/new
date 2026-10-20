"""Flask web application that displays its environment-specific configuration.

Endpoints:
    /             HTML dashboard (Bootstrap)
    /health       Liveness probe
    /ready        Readiness probe
    /api/config   JSON view of the (non-secret) configuration
"""

import logging
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template

from config import AppConfig

STARTED_AT = datetime.now(timezone.utc)


def create_app(environ=None):
    cfg = AppConfig(environ)

    app = Flask(__name__)
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["APP_CONFIG"] = cfg

    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    log = logging.getLogger("multi-env-app")
    if not cfg.environment_is_valid:
        log.warning("APP_ENV is not one of the supported environments; defaulting to 'development'")
    log.info("Starting %s v%s in %s environment", cfg.app_name, cfg.app_version, cfg.environment)

    @app.route("/")
    def dashboard():
        return render_template(
            "index.html",
            cfg=cfg,
            settings=cfg.public_settings(),
            runtime=cfg.runtime_info(),
            started_at=STARTED_AT.strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

    @app.route("/health")
    def health():
        return jsonify(status="ok"), 200

    @app.route("/ready")
    def ready():
        return jsonify(status="ready", environment=cfg.environment), 200

    @app.route("/api/config")
    def api_config():
        return jsonify(
            application=cfg.app_name,
            environment=cfg.environment,
            version=cfg.app_version,
            settings=cfg.public_settings(),
            runtime=cfg.runtime_info(),
        )

    return app


app = create_app()


if __name__ == "__main__":
    # Local development server only. In containers the app runs under gunicorn.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=app.config["APP_CONFIG"].debug)
