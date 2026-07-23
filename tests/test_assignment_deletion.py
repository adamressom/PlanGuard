from datetime import datetime, timezone

import pytest

from planguard import create_app, db
from planguard.models import Assignment, User


@pytest.fixture
def delete_setup(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "delete-test-secret", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'delete.db'}"})
    with app.app_context():
        owner = User(email="owner@example.com", display_name="Owner")
        owner.set_password("owner-password")
        other = User(email="other@example.com", display_name="Other")
        other.set_password("other-password")
        db.session.add_all([owner, other])
        db.session.flush()
        first = Assignment(user_id=owner.id, title="Delete this assignment", course="TEST 101", deadline=datetime(2026, 9, 1, tzinfo=timezone.utc), difficulty=3, estimated_minutes=60, course_weight=20, progress=0)
        keep = Assignment(user_id=owner.id, title="Keep this assignment", course="TEST 102", deadline=datetime(2026, 9, 2, tzinfo=timezone.utc), difficulty=3, estimated_minutes=60, course_weight=20, progress=0)
        private = Assignment(user_id=other.id, title="Other private assignment", course="PRIVATE 201", deadline=datetime(2026, 9, 3, tzinfo=timezone.utc), difficulty=3, estimated_minutes=60, course_weight=20, progress=0)
        db.session.add_all([first, keep, private])
        db.session.commit()
        ids = {"owner": owner.id, "other": other.id, "delete": first.id, "keep": keep.id, "private": private.id}
    return app, ids


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def test_dashboard_has_delete_control_and_confirmation(delete_setup):
    app, ids = delete_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert f'/assignments/{ids["delete"]}/delete'.encode() in response.data
    assert b"Delete this assignment" in response.data
    assert b"Keep assignment" in response.data
    assert b"Yes, delete it" in response.data


def test_detail_page_has_delete_control_and_confirmation(delete_setup):
    app, ids = delete_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.get(f'/assignments/{ids["delete"]}')
    assert response.status_code == 200
    assert b"Delete assignment" in response.data
    assert f'/assignments/{ids["delete"]}/delete'.encode() in response.data
    assert b"cannot be undone" in response.data


def test_owner_can_delete_assignment_and_it_leaves_queue(delete_setup):
    app, ids = delete_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post(f'/assignments/{ids["delete"]}/delete', follow_redirects=True)
    assert response.status_code == 200
    assert f'data-delete-url="/assignments/{ids["delete"]}/delete"'.encode() not in response.data
    assert b"Keep this assignment" in response.data
    assert b"was deleted from your plan" in response.data
    with app.app_context():
        assert db.session.get(Assignment, ids["delete"]) is None
        assert db.session.get(Assignment, ids["keep"]) is not None


def test_user_cannot_delete_another_users_assignment(delete_setup):
    app, ids = delete_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post(f'/assignments/{ids["private"]}/delete')
    assert response.status_code == 404
    with app.app_context():
        assert db.session.get(Assignment, ids["private"]) is not None


def test_anonymous_user_cannot_delete_assignment(delete_setup):
    app, ids = delete_setup
    response = app.test_client().post(f'/assignments/{ids["delete"]}/delete')
    assert response.status_code == 302
    assert "/login?next=" in response.headers["Location"]
    with app.app_context():
        assert db.session.get(Assignment, ids["delete"]) is not None
