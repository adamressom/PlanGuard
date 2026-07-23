from datetime import datetime, timedelta, timezone

import pytest

from planguard import create_app, db
from planguard.models import Assignment, IntegrationState, User


@pytest.fixture
def isolation_setup(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "isolation-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'isolation.db'}",
    })
    with app.app_context():
        first = User(email="first@example.com", display_name="First User")
        first.set_password("first-password")
        second = User(email="second@example.com", display_name="Second User")
        second.set_password("second-password")
        db.session.add_all([first, second])
        db.session.flush()

        first_assignment = Assignment(
            user_id=first.id, title="First private assignment", course="FIRST 101",
            deadline=datetime.now(timezone.utc) + timedelta(days=1), difficulty=3,
            estimated_minutes=60, course_weight=20, progress=10,
        )
        second_assignment = Assignment(
            user_id=second.id, title="Second secret assignment", course="SECOND 202",
            deadline=datetime.now(timezone.utc) + timedelta(days=2), difficulty=4,
            estimated_minutes=90, course_weight=30, progress=25,
        )
        first_integration = IntegrationState(user_id=first.id, provider="notion", status="connected")
        second_integration = IntegrationState(user_id=second.id, provider="google_calendar", status="error")
        db.session.add_all([first_assignment, second_assignment, first_integration, second_integration])
        db.session.commit()
        ids = {
            "first_user": first.id, "second_user": second.id,
            "first_assignment": first_assignment.id, "second_assignment": second_assignment.id,
            "first_integration": first_integration.id, "second_integration": second_integration.id,
        }
    return app, ids


def sign_in_as(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def test_dashboard_only_lists_signed_in_users_assignments(isolation_setup):
    app, ids = isolation_setup
    client = app.test_client()
    sign_in_as(client, ids["first_user"])
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"First private assignment" in response.data
    assert b"Second secret assignment" not in response.data


def test_assignment_page_hides_another_users_record(isolation_setup):
    app, ids = isolation_setup
    client = app.test_client()
    sign_in_as(client, ids["first_user"])
    assert client.get(f'/assignments/{ids["first_assignment"]}').status_code == 200
    assert client.get(f'/assignments/{ids["second_assignment"]}').status_code == 404


def test_anonymous_json_request_returns_401(isolation_setup):
    app, ids = isolation_setup
    response = app.test_client().get(f'/api/assignments/{ids["first_assignment"]}')
    assert response.status_code == 401
    assert response.json == {"error": "Authentication required."}


def test_assignment_json_hides_another_users_record(isolation_setup):
    app, ids = isolation_setup
    client = app.test_client()
    sign_in_as(client, ids["first_user"])
    own = client.get(f'/api/assignments/{ids["first_assignment"]}')
    other = client.get(f'/api/assignments/{ids["second_assignment"]}')
    assert own.status_code == 200
    assert own.json["title"] == "First private assignment"
    assert other.status_code == 404
    assert other.json == {"error": "Record not found."}


def test_user_cannot_update_another_users_assignment(isolation_setup):
    app, ids = isolation_setup
    client = app.test_client()
    sign_in_as(client, ids["first_user"])
    response = client.patch(f'/api/assignments/{ids["second_assignment"]}', json={"progress": 99})
    assert response.status_code == 404
    with app.app_context():
        assert db.session.get(Assignment, ids["second_assignment"]).progress == 25


def test_user_cannot_delete_another_users_assignment(isolation_setup):
    app, ids = isolation_setup
    client = app.test_client()
    sign_in_as(client, ids["first_user"])
    response = client.delete(f'/api/assignments/{ids["second_assignment"]}')
    assert response.status_code == 404
    with app.app_context():
        assert db.session.get(Assignment, ids["second_assignment"]) is not None


def test_user_can_update_and_delete_own_assignment(isolation_setup):
    app, ids = isolation_setup
    client = app.test_client()
    sign_in_as(client, ids["first_user"])
    update = client.patch(f'/api/assignments/{ids["first_assignment"]}', json={"progress": 70, "completed": True, "user_id": ids["second_user"]})
    assert update.status_code == 200
    assert update.json["progress"] == 70
    delete = client.delete(f'/api/assignments/{ids["first_assignment"]}')
    assert delete.status_code == 204
    with app.app_context():
        assert db.session.get(Assignment, ids["first_assignment"]) is None


def test_integration_json_is_isolated_by_user(isolation_setup):
    app, ids = isolation_setup
    client = app.test_client()
    sign_in_as(client, ids["first_user"])
    own = client.get(f'/api/integrations/{ids["first_integration"]}')
    other = client.get(f'/api/integrations/{ids["second_integration"]}')
    assert own.status_code == 200
    assert own.json["provider"] == "notion"
    assert other.status_code == 404


def test_user_cannot_update_or_delete_another_users_integration(isolation_setup):
    app, ids = isolation_setup
    client = app.test_client()
    sign_in_as(client, ids["first_user"])
    assert client.patch(f'/api/integrations/{ids["second_integration"]}', json={"status": "connected"}).status_code == 404
    assert client.delete(f'/api/integrations/{ids["second_integration"]}').status_code == 404
    with app.app_context():
        integration = db.session.get(IntegrationState, ids["second_integration"])
        assert integration.status == "error"
