import re
from datetime import datetime, timezone

import pytest

from planguard import create_app, db
from planguard.models import Assignment, User


@pytest.fixture
def edit_setup(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "edit-test-secret", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'edit.db'}"})
    with app.app_context():
        owner = User(email="owner@example.com", display_name="Owner")
        owner.set_password("owner-password")
        other = User(email="other@example.com", display_name="Other")
        other.set_password("other-password")
        db.session.add_all([owner, other])
        db.session.flush()
        assignment = Assignment(
            user_id=owner.id, title="Original assignment", course="PHYS 101",
            deadline=datetime(2026, 8, 15, 17, 30, tzinfo=timezone.utc), difficulty=1,
            estimated_minutes=90, course_weight=10, progress=90, completed=False,
            notes="Original notes", provider_id="original-provider",
        )
        other_assignment = Assignment(
            user_id=other.id, title="Other user's assignment", course="PRIVATE 200",
            deadline=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc), difficulty=3,
            estimated_minutes=60, course_weight=20, progress=0, completed=False,
        )
        db.session.add_all([assignment, other_assignment])
        db.session.commit()
        ids = {"owner": owner.id, "other": other.id, "assignment": assignment.id, "other_assignment": other_assignment.id}
    return app, ids


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def updated_values(**overrides):
    return {"title": "Updated assignment", "course": "PHYS 202", "deadline": "2026-08-18T19:45", "difficulty": "5", "estimated_minutes": "150", "course_impact": "100", "progress": "0", "completed": "on", "notes": "Updated notes", "provider_id": "updated-provider", **overrides}


def dashboard_score(response):
    match = re.search(rb'class="task-score"><b>(\d+)</b>', response.data)
    assert match
    return int(match.group(1))


def test_edit_form_is_populated_with_current_values(edit_setup):
    app, ids = edit_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.get(f'/assignments/{ids["assignment"]}/edit')
    assert response.status_code == 200
    assert b'value="Original assignment"' in response.data
    assert b'value="PHYS 101"' in response.data
    assert b'value="2026-08-15T17:30"' in response.data
    assert b">Original notes</textarea>" in response.data
    assert b'value="original-provider"' in response.data
    assert b"Save changes" in response.data


def test_owner_can_update_every_assignment_field(edit_setup):
    app, ids = edit_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post(f'/assignments/{ids["assignment"]}/edit', data=updated_values())
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    with app.app_context():
        assignment = db.session.get(Assignment, ids["assignment"])
        assert assignment.title == "Updated assignment"
        assert assignment.course == "PHYS 202"
        assert assignment.deadline.isoformat() == "2026-08-18T19:45:00"
        assert assignment.difficulty == 5
        assert assignment.estimated_minutes == 150
        assert assignment.course_impact == 100
        assert assignment.progress == 0
        assert assignment.completed is True
        assert assignment.notes == "Updated notes"
        assert assignment.provider_id == "updated-provider"
        assert assignment.user_id == ids["owner"]


def test_other_user_cannot_open_or_submit_edit_form(edit_setup):
    app, ids = edit_setup
    client = app.test_client()
    sign_in(client, ids["other"])
    url = f'/assignments/{ids["assignment"]}/edit'
    assert client.get(url).status_code == 404
    assert client.post(url, data=updated_values()).status_code == 404
    with app.app_context():
        assert db.session.get(Assignment, ids["assignment"]).title == "Original assignment"


def test_invalid_update_shows_errors_and_preserves_record(edit_setup):
    app, ids = edit_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post(f'/assignments/{ids["assignment"]}/edit', data=updated_values(title="", difficulty="9", progress="101"))
    assert response.status_code == 400
    assert b"Title is required." in response.data
    assert b"Difficulty must be from 1 to 5." in response.data
    assert b"Progress must be from 0 to 100." in response.data
    with app.app_context():
        assignment = db.session.get(Assignment, ids["assignment"])
        assert assignment.title == "Original assignment"
        assert assignment.difficulty == 1
        assert assignment.progress == 90


def test_saved_update_changes_dashboard_and_priority_immediately(edit_setup):
    app, ids = edit_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    before = client.get("/dashboard")
    old_score = dashboard_score(before)
    response = client.post(f'/assignments/{ids["assignment"]}/edit', data=updated_values(completed=""), follow_redirects=True)
    assert response.status_code == 200
    assert b"Updated assignment" in response.data
    assert b"Original assignment" not in response.data
    assert f'/assignments/{ids["assignment"]}/edit'.encode() in response.data
    assert b'aria-label="Edit Updated assignment"' in response.data
    assert dashboard_score(response) > old_score


def test_anonymous_user_is_redirected_from_edit_form(edit_setup):
    app, ids = edit_setup
    response = app.test_client().get(f'/assignments/{ids["assignment"]}/edit')
    assert response.status_code == 302
    assert "/login?next=" in response.headers["Location"]
