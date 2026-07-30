from sqlalchemy import inspect

from planguard import create_app, db
from planguard.models import Assignment, User, WeeklyAvailability


def app_for_database(database_path, **config):
    return create_app({
        "SECRET_KEY": "migration-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        **config,
    })


def test_non_test_startup_does_not_create_schema(tmp_path):
    app = app_for_database(tmp_path / "startup.db")

    with app.app_context():
        assert inspect(db.engine).get_table_names() == []


def test_initial_migration_upgrades_an_empty_database(tmp_path):
    app = app_for_database(tmp_path / "migrated.db")

    result = app.test_cli_runner().invoke(args=["db", "upgrade"])

    assert result.exit_code == 0, result.output
    with app.app_context():
        tables = set(inspect(db.engine).get_table_names())
    assert {
        "alembic_version",
        "assignment",
        "availability_override",
        "focus_session",
        "integration_state",
        "notion_import_source",
        "o_auth_credential",
        "scheduled_focus_block",
        "user",
        "weekly_availability",
    } <= tables


def test_demo_seed_is_idempotent(tmp_path):
    app = app_for_database(tmp_path / "seed.db", TESTING=True)
    runner = app.test_cli_runner()

    first = runner.invoke(args=["seed-demo"])
    second = runner.invoke(args=["seed-demo"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    with app.app_context():
        user = db.session.scalar(
            db.select(User).where(User.email == "demo@planguard.local")
        )
        assert user is not None
        assert db.session.scalar(
            db.select(db.func.count()).select_from(WeeklyAvailability).where(
                WeeklyAvailability.user_id == user.id
            )
        ) == 5
        assert db.session.scalar(
            db.select(db.func.count()).select_from(Assignment).where(
                Assignment.user_id == user.id,
                Assignment.provider == "seed",
            )
        ) == 2


def test_demo_seed_requires_force_in_production(tmp_path):
    app = app_for_database(
        tmp_path / "production-seed.db",
        TESTING=True,
        ENVIRONMENT="production",
    )

    result = app.test_cli_runner().invoke(args=["seed-demo"])

    assert result.exit_code != 0
    assert "Refusing to seed production" in result.output
