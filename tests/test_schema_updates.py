import sqlite3

from sqlalchemy import create_engine, inspect, text

from planguard import create_app, db


def test_existing_assignment_table_receives_new_columns(tmp_path):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """CREATE TABLE assignment (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title VARCHAR(180) NOT NULL,
            course VARCHAR(120) NOT NULL,
            deadline DATETIME NOT NULL,
            difficulty INTEGER NOT NULL,
            estimated_minutes INTEGER NOT NULL,
            course_weight FLOAT NOT NULL,
            progress INTEGER NOT NULL,
            completed BOOLEAN NOT NULL,
            created_at DATETIME
        )"""
    )
    connection.execute(
        """INSERT INTO assignment
        (id, user_id, title, course, deadline, difficulty, estimated_minutes,
         course_weight, progress, completed, created_at)
        VALUES (1, 1, 'Existing work', 'TEST 101', '2026-08-01 12:00:00',
                3, 60, 10, 0, 0, '2026-07-22 12:00:00')"""
    )
    connection.commit()
    connection.close()

    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}"})
    with app.app_context():
        columns = {column["name"] for column in inspect(db.engine).get_columns("assignment")}
        row = db.session.execute(
            text("SELECT title, notes, provider, provider_id FROM assignment WHERE id = 1")
        ).one()

    assert {"notes", "provider", "provider_id"}.issubset(columns)
    assert row.title == "Existing work"
    assert row.notes == ""
    assert row.provider == "manual"
    assert row.provider_id is None


def test_development_startup_creates_new_integration_tables_for_legacy_database(tmp_path):
    database_path = tmp_path / "legacy-development.db"
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE user ("
            "id INTEGER PRIMARY KEY, email VARCHAR(255) NOT NULL UNIQUE, "
            "display_name VARCHAR(120) NOT NULL, password_hash VARCHAR(255) NOT NULL, "
            "created_at DATETIME)"
        ))
        connection.execute(text(
            "INSERT INTO user (id, email, display_name, password_hash) "
            "VALUES (1, 'legacy@example.com', 'Legacy User', 'hashed')"
        ))

    app = create_app({
        "ENVIRONMENT": "development",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        "RATELIMIT_ENABLED": False,
    })
    with app.app_context():
        tables = set(inspect(db.engine).get_table_names())
        legacy_user = db.session.execute(
            text("SELECT email, display_name FROM user WHERE id = 1")
        ).one()

    assert {
        "integration_state",
        "o_auth_credential",
        "notion_import_source",
        "scheduled_focus_block",
    }.issubset(tables)
    assert legacy_user.email == "legacy@example.com"
    assert legacy_user.display_name == "Legacy User"


def test_existing_user_table_receives_availability_preference(tmp_path):
    database_path = tmp_path / "legacy-user.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """CREATE TABLE user (
            id INTEGER PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            display_name VARCHAR(120) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            created_at DATETIME
        )"""
    )
    connection.execute(
        "INSERT INTO user (id, email, display_name, password_hash) VALUES (1, 'legacy@example.com', 'Legacy', 'hash')"
    )
    connection.commit()
    connection.close()

    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}"})
    with app.app_context():
        columns = {column["name"] for column in inspect(db.engine).get_columns("user")}
        row = db.session.execute(text("SELECT email, available_study_minutes FROM user WHERE id = 1")).one()

    assert "available_study_minutes" in columns
    assert row.email == "legacy@example.com"
    assert row.available_study_minutes == 120


def test_existing_focus_table_receives_completed_duration_without_losing_history(tmp_path):
    database_path = tmp_path / "legacy-focus.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """CREATE TABLE focus_session (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            assignment_id INTEGER,
            assignment_title VARCHAR(180) NOT NULL,
            planned_minutes INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL,
            accumulated_seconds INTEGER NOT NULL,
            started_at DATETIME NOT NULL,
            last_resumed_at DATETIME,
            ended_at DATETIME,
            created_at DATETIME NOT NULL
        )"""
    )
    connection.execute(
        """INSERT INTO focus_session
        (id, user_id, assignment_title, planned_minutes, status, accumulated_seconds, started_at, ended_at, created_at)
        VALUES (1, 1, 'Existing session', 25, 'completed', 1500,
                '2026-07-24 12:00:00', '2026-07-24 12:25:00', '2026-07-24 12:00:00')"""
    )
    connection.commit()
    connection.close()

    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}"})
    with app.app_context():
        columns = {column["name"] for column in inspect(db.engine).get_columns("focus_session")}
        row = db.session.execute(text("SELECT assignment_title, completed_seconds FROM focus_session WHERE id = 1")).one()

    assert "completed_seconds" in columns
    assert row.assignment_title == "Existing session"
    assert row.completed_seconds == 1500
