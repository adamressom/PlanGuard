from planguard import create_app, db
from planguard.models import Assignment, User


def make_app(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "assignment-test-secret", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'assignments.db'}"})
    with app.app_context():
        user = User(email="student@example.com", display_name="Student")
        user.set_password("strong-pass-123")
        second = User(email="other@example.com", display_name="Other Student")
        second.set_password("strong-pass-456")
        db.session.add_all([user, second])
        db.session.commit()
        user_ids = (user.id, second.id)
    return app, user_ids


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def valid_assignment(**overrides):
    return {"title": "Physics problem set", "course": "PHYS 201", "deadline": "2026-08-15T17:30", "difficulty": "4", "estimated_minutes": "90", "course_impact": "22.5", "progress": "15", "completed": "on", "notes": "Complete questions 1 through 12.", "provider_id": "notion-page-123", **overrides}


def test_signed_in_user_can_open_assignment_form(tmp_path):
    app, (user_id, _) = make_app(tmp_path)
    client = app.test_client()
    sign_in(client, user_id)
    response = client.get("/assignments/new")
    assert response.status_code == 200
    assert b"Add to my plan" in response.data


def test_anonymous_user_cannot_open_assignment_form(tmp_path):
    app, _ = make_app(tmp_path)
    response = app.test_client().get("/assignments/new")
    assert response.status_code == 302
    assert "/login?next=/assignments/new" in response.headers["Location"]


def test_assignment_creation_stores_every_supported_field(tmp_path):
    app, (user_id, _) = make_app(tmp_path)
    client = app.test_client()
    sign_in(client, user_id)
    response = client.post("/assignments/new", data=valid_assignment())
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    with app.app_context():
        assignment = db.session.scalar(db.select(Assignment))
        assert assignment.user_id == user_id
        assert assignment.title == "Physics problem set"
        assert assignment.course == "PHYS 201"
        assert assignment.deadline.isoformat() == "2026-08-15T17:30:00"
        assert assignment.difficulty == 4
        assert assignment.estimated_minutes == 90
        assert assignment.course_impact == 22.5
        assert assignment.progress == 15
        assert assignment.completed is True
        assert assignment.notes == "Complete questions 1 through 12."
        assert assignment.provider_id == "notion-page-123"


def test_assignment_ownership_cannot_be_overridden_by_form(tmp_path):
    app, (user_id, other_user_id) = make_app(tmp_path)
    client = app.test_client()
    sign_in(client, user_id)
    client.post("/assignments/new", data=valid_assignment(user_id=str(other_user_id)))
    with app.app_context():
        assert db.session.scalar(db.select(Assignment)).user_id == user_id


def test_new_assignment_appears_on_dashboard(tmp_path):
    app, (user_id, _) = make_app(tmp_path)
    client = app.test_client()
    sign_in(client, user_id)
    response = client.post("/assignments/new", data=valid_assignment(completed=""), follow_redirects=True)
    assert response.status_code == 200
    assert b"Physics problem set" in response.data
    assert b"PHYS 201" in response.data


def test_optional_fields_can_be_blank(tmp_path):
    app, (user_id, _) = make_app(tmp_path)
    client = app.test_client()
    sign_in(client, user_id)
    response = client.post("/assignments/new", data=valid_assignment(notes="", provider_id="", completed="", progress=""))
    assert response.status_code == 302
    with app.app_context():
        assignment = db.session.scalar(db.select(Assignment))
        assert assignment.notes == ""
        assert assignment.provider_id is None
        assert assignment.progress == 0
        assert assignment.completed is False


def test_missing_required_fields_show_clear_errors(tmp_path):
    app, (user_id, _) = make_app(tmp_path)
    client = app.test_client()
    sign_in(client, user_id)
    response = client.post("/assignments/new", data=valid_assignment(title="", course="", deadline=""))
    assert response.status_code == 400
    assert b"Title is required." in response.data
    assert b"Course is required." in response.data
    assert b"Deadline is required." in response.data
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(Assignment)) == 0


def test_invalid_numeric_ranges_are_rejected(tmp_path):
    app, (user_id, _) = make_app(tmp_path)
    client = app.test_client()
    sign_in(client, user_id)
    response = client.post("/assignments/new", data=valid_assignment(difficulty="6", estimated_minutes="0", course_impact="101", progress="-1"))
    assert response.status_code == 400
    assert b"Difficulty must be from 1 to 5." in response.data
    assert b"Estimated minutes must be from 1 to 1440." in response.data
    assert b"Course impact must be from 0 to 100." in response.data
    assert b"Progress must be from 0 to 100." in response.data


def test_non_numeric_values_and_invalid_deadline_are_rejected(tmp_path):
    app, (user_id, _) = make_app(tmp_path)
    client = app.test_client()
    sign_in(client, user_id)
    response = client.post("/assignments/new", data=valid_assignment(difficulty="hard", estimated_minutes="soon", course_impact="high", progress="some", deadline="tomorrow"))
    assert response.status_code == 400
    assert b"Difficulty must be a whole number from 1 to 5." in response.data
    assert b"Estimated minutes must be a whole number from 1 to 1440." in response.data
    assert b"Course impact must be a number from 0 to 100." in response.data
    assert b"Enter a valid deadline." in response.data
