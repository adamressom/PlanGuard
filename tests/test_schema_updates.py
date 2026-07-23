import sqlite3

from sqlalchemy import inspect, text

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
        row = db.session.execute(text("SELECT title, notes, provider_id FROM assignment WHERE id = 1")).one()

    assert {"notes", "provider_id"}.issubset(columns)
    assert row.title == "Existing work"
    assert row.notes == ""
    assert row.provider_id is None
