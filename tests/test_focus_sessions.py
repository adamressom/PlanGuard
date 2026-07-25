from datetime import datetime, timedelta, timezone

import pytest

from planguard import create_app, db
from planguard.models import Assignment, FocusSession, User
from planguard.services.focus import FocusStateError, elapsed_seconds, end_focus_session, pause_focus_session, resume_focus_session, start_focus_session


@pytest.fixture
def focus_setup(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "focus-secret", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'focus.db'}"})
    with app.app_context():
        owner = User(email="owner@example.com", display_name="Owner", available_study_minutes=45)
        owner.set_password("owner-password")
        other = User(email="other@example.com", display_name="Other")
        other.set_password("other-password")
        db.session.add_all([owner, other])
        db.session.flush()
        assignment = Assignment(user_id=owner.id, title="Priority project", course="CS 401", deadline=datetime.now(timezone.utc) + timedelta(hours=4), difficulty=5, estimated_minutes=60, course_weight=40, progress=10)
        private = Assignment(user_id=other.id, title="Private project", course="CS 402", deadline=datetime.now(timezone.utc) + timedelta(days=1), difficulty=3, estimated_minutes=30, course_weight=20, progress=0)
        completed = Assignment(user_id=owner.id, title="Finished project", course="CS 403", deadline=datetime.now(timezone.utc) + timedelta(days=2), difficulty=2, estimated_minutes=20, course_weight=10, progress=100, completed=True)
        db.session.add_all([assignment, private, completed])
        db.session.commit()
        ids = {"owner": owner.id, "other": other.id, "assignment": assignment.id, "private": private.id, "completed": completed.id}
    return app, ids


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def test_focus_service_pause_resume_and_end(focus_setup):
    app, ids = focus_setup
    start = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    with app.app_context():
        session = start_focus_session(ids["owner"], db.session.get(Assignment, ids["assignment"]), 25, now=start)
        assert elapsed_seconds(session, start + timedelta(seconds=12)) == 12
        pause_focus_session(session, now=start + timedelta(seconds=20))
        assert session.status == "paused"
        assert elapsed_seconds(session, start + timedelta(minutes=5)) == 20
        resume_focus_session(session, now=start + timedelta(minutes=5))
        assert elapsed_seconds(session, start + timedelta(minutes=5, seconds=7)) == 27
        end_focus_session(session, now=start + timedelta(minutes=5, seconds=10))
        assert session.status == "ended"
        assert session.accumulated_seconds == 30


def test_completed_timer_and_invalid_state(focus_setup):
    app, ids = focus_setup
    start = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    with app.app_context():
        session = start_focus_session(ids["owner"], db.session.get(Assignment, ids["assignment"]), 1, now=start)
        end_focus_session(session, timer_complete=True, now=start + timedelta(minutes=1))
        assert session.status == "completed"
        assert session.accumulated_seconds == 60
        with pytest.raises(FocusStateError):
            resume_focus_session(session)


def test_owner_can_start_pause_resume_and_end(focus_setup):
    app, ids = focus_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    started = client.post("/api/focus-sessions", json={"assignment_id": ids["assignment"], "planned_minutes": 25})
    assert started.status_code == 201
    session_id = started.get_json()["session"]["id"]
    assert client.get("/api/focus-sessions/active").get_json()["session"]["id"] == session_id
    assert client.post(f"/api/focus-sessions/{session_id}/pause").get_json()["session"]["status"] == "paused"
    assert client.post(f"/api/focus-sessions/{session_id}/resume").get_json()["session"]["status"] == "running"
    ended = client.post(f"/api/focus-sessions/{session_id}/end", json={"reason": "manual"})
    assert ended.get_json()["session"]["status"] == "ended"
    assert client.get("/api/focus-sessions/active").get_json() == {"session": None}


@pytest.mark.parametrize("minutes", [0, 241, 2.5, "25", None, True])
def test_invalid_durations_are_rejected(focus_setup, minutes):
    app, ids = focus_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post("/api/focus-sessions", json={"assignment_id": ids["assignment"], "planned_minutes": minutes})
    assert response.status_code == 400
    assert "whole number from 1 to 240" in response.get_json()["error"]


def test_duplicate_active_and_completed_assignment_are_rejected(focus_setup):
    app, ids = focus_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    assert client.post("/api/focus-sessions", json={"assignment_id": ids["assignment"], "planned_minutes": 25}).status_code == 201
    duplicate = client.post("/api/focus-sessions", json={"assignment_id": ids["assignment"], "planned_minutes": 25})
    assert duplicate.status_code == 409
    active = client.get("/api/focus-sessions/active").get_json()["session"]
    client.post(f"/api/focus-sessions/{active['id']}/end", json={"reason": "manual"})
    assert client.post("/api/focus-sessions", json={"assignment_id": ids["completed"], "planned_minutes": 20}).status_code == 400


def test_anonymous_and_cross_user_access_is_rejected(focus_setup):
    app, ids = focus_setup
    anonymous = app.test_client()
    assert anonymous.get("/api/focus-sessions/active").status_code == 401
    assert anonymous.post("/api/focus-sessions", json={"assignment_id": ids["assignment"], "planned_minutes": 25}).status_code == 401
    owner = app.test_client()
    sign_in(owner, ids["owner"])
    assert owner.post("/api/focus-sessions", json={"assignment_id": ids["private"], "planned_minutes": 25}).status_code == 404
    session_id = owner.post("/api/focus-sessions", json={"assignment_id": ids["assignment"], "planned_minutes": 25}).get_json()["session"]["id"]
    other = app.test_client()
    sign_in(other, ids["other"])
    for action in ("pause", "resume", "end"):
        assert other.post(f"/api/focus-sessions/{session_id}/{action}").status_code == 404


def test_invalid_transitions_return_conflict(focus_setup):
    app, ids = focus_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    session_id = client.post("/api/focus-sessions", json={"assignment_id": ids["assignment"], "planned_minutes": 25}).get_json()["session"]["id"]
    assert client.post(f"/api/focus-sessions/{session_id}/resume").status_code == 409
    assert client.post(f"/api/focus-sessions/{session_id}/pause").status_code == 200
    assert client.post(f"/api/focus-sessions/{session_id}/pause").status_code == 409


def test_dashboard_start_control_is_recommended_and_accessible(focus_setup):
    app, ids = focus_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.get("/dashboard")
    assert f'data-assignment-id="{ids["assignment"]}"'.encode() in response.data
    assert b'data-planned-minutes="45"' in response.data
    assert b'<button class="button ghost" type="button" data-focus ' in response.data
    assert b'data-focus-start' in response.data
    assert b'role="status" aria-live="polite"' in response.data


def test_active_focus_survives_refresh_and_has_keyboard_controls(focus_setup):
    app, ids = focus_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    session = client.post("/api/focus-sessions", json={"assignment_id": ids["assignment"], "planned_minutes": 25}).get_json()["session"]
    for response in (client.get("/dashboard"), client.get("/dashboard")):
        assert f'data-session-id="{session["id"]}"'.encode() in response.data
        assert b'role="timer" aria-label="Focus time remaining"' in response.data
        assert b'<button class="focus-control pause" type="button" data-focus-pause' in response.data
        assert b'<button class="focus-control end" type="button" data-focus-end' in response.data
        assert b"persists across refreshes" in response.data


def test_paused_focus_shows_resume(focus_setup):
    app, ids = focus_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    session_id = client.post("/api/focus-sessions", json={"assignment_id": ids["assignment"], "planned_minutes": 25}).get_json()["session"]["id"]
    client.post(f"/api/focus-sessions/{session_id}/pause")
    response = client.get("/dashboard")
    assert b'data-focus-resume' in response.data
    assert b'class="focus-state paused"' in response.data


def test_deletion_removes_active_and_retains_finished_history(focus_setup):
    app, ids = focus_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    active_id = client.post("/api/focus-sessions", json={"assignment_id": ids["assignment"], "planned_minutes": 25}).get_json()["session"]["id"]
    assert client.delete(f"/api/assignments/{ids['assignment']}").status_code == 204
    with app.app_context():
        assert db.session.get(FocusSession, active_id) is None
        assignment = db.session.get(Assignment, ids["completed"])
        history = FocusSession(user_id=ids["owner"], assignment_id=assignment.id, assignment_title=assignment.title, planned_minutes=20, status="completed", accumulated_seconds=1200, started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc))
        db.session.add(history)
        db.session.commit()
        history_id = history.id
    assert client.delete(f"/api/assignments/{ids['completed']}").status_code == 204
    with app.app_context():
        retained = db.session.get(FocusSession, history_id)
        assert retained.assignment_id is None
        assert retained.assignment_title == "Finished project"
