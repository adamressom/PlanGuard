from datetime import datetime, timedelta, timezone

from planguard import create_app, db
from planguard.models import Assignment, User


def make_app(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "explanation-test-secret", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'explanations.db'}"})
    now = datetime.now(timezone.utc)
    with app.app_context():
        user = User(email="student@example.com", display_name="Student", available_study_minutes=90)
        user.set_password("student-password")
        db.session.add(user)
        db.session.flush()
        first = Assignment(user_id=user.id, title="Explainable project", course="TRUST 401", deadline=now + timedelta(hours=5), difficulty=5, estimated_minutes=60, course_weight=45, progress=10, completed=False)
        second = Assignment(user_id=user.id, title="Explainable reading", course="TRUST 102", deadline=now + timedelta(days=8), difficulty=2, estimated_minutes=120, course_weight=10, progress=60, completed=False)
        db.session.add_all([first, second])
        db.session.commit()
        user_id = user.id
    return app, user_id


def dashboard(tmp_path):
    app, user_id = make_app(tmp_path)
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = user_id
    return client.get("/dashboard")


def test_each_active_assignment_row_has_score_explanation_control(tmp_path):
    response = dashboard(tmp_path)
    assert response.status_code == 200
    assert response.data.count(b"Why this score?") == 2
    assert response.data.count(b'class="score-explanation"') == 2


def test_explanation_ui_contains_every_required_factor(tmp_path):
    response = dashboard(tmp_path)
    for label in (b"Deadline urgency", b"Difficulty", b"Course impact", b"Time fit", b"Current progress"):
        assert response.data.count(label) >= 2
    assert b"deadline + difficulty + course impact + time fit" in response.data


def test_explanation_ui_shows_final_score_and_plain_language_summary(tmp_path):
    response = dashboard(tmp_path)
    assert b"out of 100" in response.data
    assert b"priority because" in response.data or b"priority:" in response.data
    assert b"other work may need attention first" in response.data


def test_explanation_disclosures_have_unique_accessible_regions(tmp_path):
    response = dashboard(tmp_path)
    assert b'aria-controls="score-details-1"' in response.data
    assert b'aria-controls="score-details-2"' in response.data
    assert b'aria-label="Priority explanation for Explainable project"' in response.data
    assert b'aria-label="Priority explanation for Explainable reading"' in response.data
