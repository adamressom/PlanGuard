import os
from datetime import timedelta

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import inspect, text

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)


def apply_schema_updates():
    """Apply small, additive SQLite updates while the project is pre-migrations."""
    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()
    statements = []
    if "assignment" in table_names:
        assignment_columns = {column["name"] for column in inspector.get_columns("assignment")}
        if "notes" not in assignment_columns:
            statements.append("ALTER TABLE assignment ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        if "provider_id" not in assignment_columns:
            statements.append("ALTER TABLE assignment ADD COLUMN provider_id VARCHAR(255)")
        if "provider" not in assignment_columns:
            statements.append("ALTER TABLE assignment ADD COLUMN provider VARCHAR(40) NOT NULL DEFAULT 'manual'")
    if "user" in table_names:
        user_columns = {column["name"] for column in inspector.get_columns("user")}
        if "available_study_minutes" not in user_columns:
            statements.append("ALTER TABLE user ADD COLUMN available_study_minutes INTEGER NOT NULL DEFAULT 120")
    if "focus_session" in table_names:
        focus_columns = {column["name"] for column in inspector.get_columns("focus_session")}
        if "completed_seconds" not in focus_columns:
            statements.append("ALTER TABLE focus_session ADD COLUMN completed_seconds INTEGER")
    if "integration_state" in table_names:
        integration_columns = {column["name"] for column in inspector.get_columns("integration_state")}
        additions = {
            "mode": "VARCHAR(20)",
            "provider_account_id": "VARCHAR(255)",
            "provider_account_email": "VARCHAR(255)",
            "granted_scopes": "JSON",
            "last_error_code": "VARCHAR(80)",
            "connected_at": "DATETIME",
            "last_sync_attempt_at": "DATETIME",
            "sync_status": "VARCHAR(20) NOT NULL DEFAULT 'never'",
        }
        for column, definition in additions.items():
            if column not in integration_columns:
                statements.append(f"ALTER TABLE integration_state ADD COLUMN {column} {definition}")

    if statements:
        with db.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
            if "focus_session" in table_names:
                connection.execute(text(
                    "UPDATE focus_session SET completed_seconds = accumulated_seconds "
                    "WHERE completed_seconds IS NULL AND status IN ('completed', 'ended')"
                ))


def create_app(test_config=None):
    environment = os.getenv("FLASK_ENV", "development")
    secret_key = os.getenv("SECRET_KEY")
    if environment == "production" and not secret_key:
        raise RuntimeError("SECRET_KEY must be configured in production")

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        ENVIRONMENT=environment,
        SECRET_KEY=secret_key or "dev-only-change-me",
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///planguard.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=environment == "production",
        SESSION_COOKIE_NAME="__Host-planguard" if environment == "production" else "planguard",
        SESSION_COOKIE_PATH="/",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        WTF_CSRF_TIME_LIMIT=7200,
        RATELIMIT_STORAGE_URI=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        AUTH_RATE_LIMIT=os.getenv("AUTH_RATE_LIMIT", "10 per minute"),
        GOOGLE_CALENDAR_MODE=os.getenv("GOOGLE_CALENDAR_MODE", "demo").strip().lower(),
        GOOGLE_CLIENT_ID=os.getenv("GOOGLE_CLIENT_ID", ""),
        GOOGLE_CLIENT_SECRET=os.getenv("GOOGLE_CLIENT_SECRET", ""),
        GOOGLE_OAUTH_REDIRECT_URI=os.getenv("GOOGLE_OAUTH_REDIRECT_URI", ""),
        TOKEN_ENCRYPTION_KEY=os.getenv("TOKEN_ENCRYPTION_KEY", ""),
        TOKEN_ENCRYPTION_KEY_VERSION=os.getenv("TOKEN_ENCRYPTION_KEY_VERSION", "v1"),
        DEFAULT_TIMEZONE=os.getenv("DEFAULT_TIMEZONE", "America/New_York"),
        NOTION_MODE=os.getenv("NOTION_MODE", "demo").strip().lower(),
        NOTION_CLIENT_ID=os.getenv("NOTION_CLIENT_ID", ""),
        NOTION_CLIENT_SECRET=os.getenv("NOTION_CLIENT_SECRET", ""),
        NOTION_OAUTH_REDIRECT_URI=os.getenv("NOTION_OAUTH_REDIRECT_URI", ""),
    )
    if test_config:
        app.config.update(test_config)
    app.config.setdefault("WTF_CSRF_ENABLED", not app.config.get("TESTING", False))
    app.config.setdefault("RATELIMIT_ENABLED", not app.config.get("TESTING", False))

    mode = app.config["GOOGLE_CALENDAR_MODE"]
    if mode not in {"disabled", "demo", "live"}:
        raise RuntimeError("GOOGLE_CALENDAR_MODE must be disabled, demo, or live")
    required_live_settings = (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_OAUTH_REDIRECT_URI",
        "TOKEN_ENCRYPTION_KEY",
    )
    missing_live_settings = [key for key in required_live_settings if not app.config.get(key)]
    app.config["GOOGLE_OAUTH_CONFIGURED"] = mode != "live" or not missing_live_settings
    if mode == "live" and environment == "production" and missing_live_settings:
        raise RuntimeError(
            "Live Google Calendar requires: " + ", ".join(missing_live_settings)
        )
    notion_mode = app.config["NOTION_MODE"]
    if notion_mode not in {"disabled", "demo", "live"}:
        raise RuntimeError("NOTION_MODE must be disabled, demo, or live")
    required_notion_settings = (
        "NOTION_CLIENT_ID",
        "NOTION_CLIENT_SECRET",
        "NOTION_OAUTH_REDIRECT_URI",
        "TOKEN_ENCRYPTION_KEY",
    )
    missing_notion_settings = [key for key in required_notion_settings if not app.config.get(key)]
    app.config["NOTION_OAUTH_CONFIGURED"] = notion_mode != "live" or not missing_notion_settings
    if notion_mode == "live" and environment == "production" and missing_notion_settings:
        raise RuntimeError(
            "Live Notion requires: " + ", ".join(missing_notion_settings)
        )

    db.init_app(app)
    migrate.init_app(app, db, compare_type=True, render_as_batch=True)
    csrf.init_app(app)
    limiter.init_app(app)

    from .routes import main
    from .auth import auth
    from .api import api
    from .commands import register_commands
    app.register_blueprint(main)
    app.register_blueprint(auth)
    app.register_blueprint(api)
    register_commands(app)

    if app.config.get("TESTING"):
        with app.app_context():
            db.create_all()
            apply_schema_updates()

    return app
