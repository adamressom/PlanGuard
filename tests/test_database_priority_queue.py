from datetime import datetime, timedelta, timezone

import pytest

from planguard import create_app, db
from planguard.models import Assignment, User


@pytest.fixture
def queue_setup(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "queue-test-secret", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'queue.db'}"})
    now = datetime.now(timezone.utc)
    with app.app_context():
        owner = User(email="owner@example.com", display_name="Queue Owner")
        owner.set_password("owner-password")
        other = User(email="other@example.com", display_name="Other User")
        other.set_password("other-password")
        db.session.add_all([owner, other])
        db.session.flush()
        top = Assignment(user_id=owner.id, title="Critical overdue project", course="CAP 401", deadline=now - timedelta(days=3), difficulty=5, estimated_minutes=45, course_weight=100, progress=0, completed=False)
        low = Assignment(user_id=owner.id, title="Low priority reading", course="READ 101", deadline=now + timedelta(days=20), difficulty=1, estimated_minutes=5000, course_weight=1, progress=90, completed=False)
        edge = Assignment(user_id=owner.id, title="Zero minute edge case", course="EDGE 200", deadline=now + timedelta(days=2), difficulty=3, estimated_minutes=0, course_weight=10, progress=0, completed=False)
        done = Assignment(user_id=owner.id, title="Completed private work", course="DONE 100", deadline=now - timedelta(days=1), difficulty=5, estimated_minutes=30, course_weight=100, progress=100, completed=True)
        foreign = Assignment(user_id=other.id, title="Other user's urgent secret", course="PRIVATE 999", deadline=now - timedelta(days=30), difficulty=5, estimated_minutes=1, course_weight=100, progress=0, completed=False)
        db.session.add_all([low, edge, top, done, foreign])
        db.session.commit()
        ids = {"owner": owner.id, "top": top.id, "low": low.id, "edge": edge.id, "done": done.id}
    return app, ids


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def active_queue_html(response):
    return response.data.split(b"ACTIVE PRIORITY QUEUE", 1)[1].split(b'class="panel completed-queue"', 1)[0]


def test_dashboard_ranks_only_signed_in_users_active_database_records(queue_setup):
    app, ids = queue_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.get("/dashboard")
    active = active_queue_html(response)
    assert response.status_code == 200
    assert b"Critical overdue project" in active
    assert b"Low priority reading" in active
    assert b"Zero minute edge case" in active
    assert b"Completed private work" not in active
    assert b"Other user&#39;s urgent secret" not in response.data


def test_highest_priority_assignment_is_first_and_highlighted(queue_setup):
    app, ids = queue_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.get("/dashboard")
    active = active_queue_html(response)
    assert active.index(b"Critical overdue project") < active.index(b"Zero minute edge case")
    assert active.index(b"Zero minute edge case") < active.index(b"Low priority reading")
    assert b"top-recommendation" in active
    assert b"Top priority" in active
    assert b"#1 recommendation" in response.data


def test_top_recommendation_card_matches_first_ranked_assignment(queue_setup):
    app, ids = queue_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.get("/dashboard")
    assert response.data.count(b"Critical overdue project") >= 2
    assert b"priority score" in response.data


def test_overdue_assignment_is_clearly_labeled(queue_setup):
    app, ids = queue_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.get("/dashboard")
    assert b"overdue-task" in response.data
    assert b"Overdue by 3d" in response.data
    assert b"due-badge overdue" in response.data


def test_zero_estimate_edge_case_does_not_crash_dashboard(queue_setup):
    app, ids = queue_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"Zero minute edge case" in response.data
