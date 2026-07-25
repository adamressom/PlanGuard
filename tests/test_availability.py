from datetime import datetime, timedelta, timezone

import pytest

from planguard import create_app, db
from planguard.models import Assignment, User


@pytest.fixture
def availability_setup(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "availability-test-secret", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'availability.db'}"})
    deadline = datetime.now(timezone.utc) + timedelta(days=10)
    with app.app_context():
        owner = User(email="owner@example.com", display_name="Owner", available_study_minutes=120)
        owner.set_password("owner-password")
        other = User(email="other@example.com", display_name="Other", available_study_minutes=45)
        other.set_password("other-password")
        db.session.add_all([owner, other])
        db.session.flush()
        short = Assignment(user_id=owner.id, title="Short study task", course="SHORT 101", deadline=deadline, difficulty=3, estimated_minutes=30, course_weight=10, progress=0, completed=False)
        long = Assignment(user_id=owner.id, title="Long difficult task", course="LONG 401", deadline=deadline, difficulty=5, estimated_minutes=240, course_weight=10, progress=0, completed=False)
        db.session.add_all([short, long])
        db.session.commit()
        ids = {"owner": owner.id, "other": other.id, "short": short.id, "long": long.id}
    return app, ids


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def active_queue(response):
    return response.data.split(b"ACTIVE PRIORITY QUEUE", 1)[1].split(b'class="panel completed-queue"', 1)[0]


def test_dashboard_offers_presets_and_custom_availability_input(availability_setup):
    app, ids = availability_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"Today's capacity" in response.data
    assert b"<strong>120</strong> minutes to study" in response.data
    for value in (30, 60, 120, 180, 240):
        assert f'value="{value}"'.encode() in response.data
    assert b'id="available-minutes"' in response.data


@pytest.mark.parametrize("minutes", [0, 30, 180, 1440])
def test_valid_availability_values_persist_to_account(availability_setup, minutes):
    app, ids = availability_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post("/preferences/availability", data={"available_minutes": str(minutes)})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(User, ids["owner"]).available_study_minutes == minutes
        assert db.session.get(User, ids["other"]).available_study_minutes == 45


@pytest.mark.parametrize("value", ["-1", "1441", "1.5", "many", ""])
def test_invalid_availability_is_rejected_with_clear_feedback(availability_setup, value):
    app, ids = availability_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post("/preferences/availability", data={"available_minutes": value}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Available study time must be a whole number from 0 to 1440 minutes." in response.data
    with app.app_context():
        assert db.session.get(User, ids["owner"]).available_study_minutes == 120


def test_availability_change_recalculates_and_can_change_top_recommendation(availability_setup):
    app, ids = availability_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    limited = client.post("/preferences/availability", data={"available_minutes": "30"}, follow_redirects=True)
    limited_queue = active_queue(limited)
    assert limited_queue.index(b"Short study task") < limited_queue.index(b"Long difficult task")
    assert b"Fits your 30-minute window" in limited.data

    spacious = client.post("/preferences/availability", data={"available_minutes": "240"}, follow_redirects=True)
    spacious_queue = active_queue(spacious)
    assert spacious_queue.index(b"Long difficult task") < spacious_queue.index(b"Short study task")
    assert b"Fits your 240-minute window" in spacious.data


def test_recommendation_explains_when_task_exceeds_available_time(availability_setup):
    app, ids = availability_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post("/preferences/availability", data={"available_minutes": "1"}, follow_redirects=True)
    assert b"Needs 239 more minutes" in response.data
    assert b'time-fit exceeds' in response.data


def test_zero_availability_disables_focus_action(availability_setup):
    app, ids = availability_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post("/preferences/availability", data={"available_minutes": "0"}, follow_redirects=True)
    assert b"No study time available" in response.data
    assert b"data-focus disabled" in response.data


def test_availability_survives_sign_out_and_new_sign_in(availability_setup):
    app, ids = availability_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    client.post("/preferences/availability", data={"available_minutes": "180"})
    client.post("/logout")
    response = client.post("/login", data={"email": "owner@example.com", "password": "owner-password"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"<strong>180</strong> minutes to study" in response.data
    with app.app_context():
        assert db.session.get(User, ids["owner"]).available_study_minutes == 180


def test_anonymous_user_cannot_change_availability(availability_setup):
    app, ids = availability_setup
    response = app.test_client().post("/preferences/availability", data={"available_minutes": "300"})
    assert response.status_code == 302
    assert "/login?next=" in response.headers["Location"]
    with app.app_context():
        assert db.session.get(User, ids["owner"]).available_study_minutes == 120
