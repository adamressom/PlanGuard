import os
from datetime import timedelta

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

db = SQLAlchemy()


def apply_schema_updates():
    """Apply small, additive SQLite updates while the project is pre-migrations."""
    inspector = inspect(db.engine)
    if "assignment" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("assignment")}
    statements = []
    if "notes" not in columns:
        statements.append("ALTER TABLE assignment ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
    if "provider_id" not in columns:
        statements.append("ALTER TABLE assignment ADD COLUMN provider_id VARCHAR(255)")

    if statements:
        with db.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))


def create_app(test_config=None):
    environment = os.getenv("FLASK_ENV", "development")
    secret_key = os.getenv("SECRET_KEY")
    if environment == "production" and not secret_key:
        raise RuntimeError("SECRET_KEY must be configured in production")

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=secret_key or "dev-only-change-me",
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///planguard.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=environment == "production",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)

    from .routes import main
    from .auth import auth
    app.register_blueprint(main)
    app.register_blueprint(auth)

    with app.app_context():
        db.create_all()
        apply_schema_updates()

    return app
