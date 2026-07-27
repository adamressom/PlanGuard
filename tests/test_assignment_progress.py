import re
from datetime import datetime, timezone

import pytest

from planguard import create_app, db
from planguard.models import Assignment, User
from planguard.services.assignments import set_assignment_status


@pytest.fixture
def progress_setup(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "progress-test-secret", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'progress.db'}"})
    with app.app_context():
        owner = User(email="owner@example.com", display_name="Owner")
        owner.set_password("owner-password")
        other = User(email="other@example.com", display_name="Other")
        other.set_password("other-password")
        db.session.add_all([owner, other])
        db.session.flush()
        active = Assignment(user_id=owner.id, title="Active assignment", course="ACTIVE 101", deadline=datetime(2026, 8, 1, tzinfo=timezone.utc), difficulty=4, estimated_minutes=60, course_weight=40, progress=20, completed=False)
        completed = Assignment(user_id=owner.id, title="Finished assignment", course="DONE 201", deadline=datetime(2026, 7, 20, tzinfo=timezone.utc), difficulty=3, estimated_minutes=45, course_weight=20, progress=100, completed=True)
        private = Assignment(user_id=other.id, title="Private assignment", course="PRIVATE 301", deadline=datetime(2026, 8, 2, tzinfo=timezone.utc), difficulty=5, estimated_minutes=90, course_weight=50, progress=10, completed=False)
        db.session.add_all([active, completed, private])
        db.session.commit()
        ids = {"owner": owner.id, "other": other.id, "active": active.id, "completed": completed.id, "private": private.id}
    return app, ids


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def active_section(response):
    return response.data.split(b"ACTIVE PRIORITY QUEUE", 1)[1].split(b'class="panel completed-queue"', 1)[0]


def completed_section(response):
    return response.data.split(b'class="panel completed-queue"', 1)[1]


def score(response):
    match = re.search(rb'class="task-score"><b>(\d+)</b>', response.data)
    assert match
    return int(match.group(1))


@pytest.mark.parametrize("value", [0, 100])
def test_progress_accepts_boundary_values(progress_setup, value):
    app, ids = progress_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post(f'/assignments/{ids["active"]}/progress', data={"action": "save_progress", "progress": str(value)})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Assignment, ids["active"]).progress == value


@pytest.mark.parametrize("value", ["-1", "101", "not-a-number"])
def test_invalid_progress_is_rejected_without_changing_record(progress_setup, value):
    app, ids = progress_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post(f'/assignments/{ids["active"]}/progress', data={"action": "save_progress", "progress": value}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Progress must be a whole number from 0 to 100." in response.data
    with app.app_context():
        assert db.session.get(Assignment, ids["active"]).progress == 20


def test_mark_complete_moves_assignment_out_of_active_queue(progress_setup):
    app, ids = progress_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post(f'/assignments/{ids["active"]}/progress', data={"action": "mark_complete"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Active assignment" not in active_section(response)
    assert b"Active assignment" in completed_section(response)
    with app.app_context():
        assignment = db.session.get(Assignment, ids["active"])
        assert assignment.completed is True
        assert assignment.progress == 100


def test_mark_incomplete_returns_assignment_to_ranked_queue(progress_setup):
    app, ids = progress_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post(f'/assignments/{ids["completed"]}/progress', data={"action": "mark_incomplete"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Finished assignment" in active_section(response)
    with app.app_context():
        assert db.session.get(Assignment, ids["completed"]).completed is False


def test_progress_change_recalculates_priority_immediately(progress_setup):
    app, ids = progress_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    before_score = score(client.get("/dashboard"))
    response = client.post(f'/assignments/{ids["active"]}/progress', data={"action": "save_progress", "progress": "90"}, follow_redirects=True)
    assert response.status_code == 200
    assert score(response) < before_score
    assert b"90%" in response.data


def test_dashboard_visually_separates_active_and_completed_work(progress_setup):
    app, ids = progress_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.get("/dashboard")
    assert b"ACTIVE PRIORITY QUEUE" in response.data
    assert b"Finished work" in response.data
    assert b"Mark incomplete" in response.data
    assert b"Active assignment" in active_section(response)
    assert b"Finished assignment" not in active_section(response)


def test_user_cannot_change_another_users_progress(progress_setup):
    app, ids = progress_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post(f'/assignments/{ids["private"]}/progress', data={"action": "mark_complete"})
    assert response.status_code == 404
    with app.app_context():
        assignment = db.session.get(Assignment, ids["private"])
        assert assignment.progress == 10
        assert assignment.completed is False


def test_anonymous_user_cannot_change_progress(progress_setup):
    app, ids = progress_setup
    response = app.test_client().post(f'/assignments/{ids["active"]}/progress', data={"action": "mark_complete"})
    assert response.status_code == 302
    assert "/login?next=" in response.headers["Location"]


def test_assignment_status_service_accepts_boundary_progress(progress_setup):
    app, ids = progress_setup
    with app.app_context():
        assignment = db.session.get(Assignment, ids["active"])
        updated, errors = set_assignment_status(assignment, progress=0)
        assert errors == {}
        assert updated.progress == 0

        updated, errors = set_assignment_status(assignment, progress=100)
        assert errors == {}
        assert updated.progress == 100


def test_assignment_status_service_rejects_invalid_progress(progress_setup):
    app, ids = progress_setup
    with app.app_context():
        assignment = db.session.get(Assignment, ids["active"])
        for value in (-1, 101, "50", True):
            updated, errors = set_assignment_status(assignment, progress=value)
            assert updated is None
            assert errors == {"progress": "Progress must be a whole number from 0 to 100."}


def test_assignment_status_service_does_not_round_progress(progress_setup):
    app, ids = progress_setup
    with app.app_context():
        assignment = db.session.get(Assignment, ids["active"])
        updated, errors = set_assignment_status(assignment, progress=54)
        assert errors == {}
        assert updated.progress == 54
