from datetime import datetime, timedelta, timezone

import pytest

from planguard import create_app, db
from planguard.models import Assignment, IntegrationState, User


@pytest.fixture
def api_setup(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "api-v1-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'api-v1.db'}",
        "GOOGLE_CALENDAR_MODE": "demo",
        "NOTION_MODE": "demo",
    })
    with app.app_context():
        owner = User(email="api-owner@example.com", display_name="API Owner", available_study_minutes=90)
        owner.set_password("password123")
        other = User(email="api-other@example.com", display_name="API Other")
        other.set_password("password123")
        db.session.add_all([owner, other])
        db.session.flush()
        private = Assignment(
            user_id=other.id,
            title="Private assignment",
            course="PRIVATE 101",
            deadline=datetime.now(timezone.utc) + timedelta(days=2),
            difficulty=3,
            estimated_minutes=60,
            course_weight=10,
            progress=0,
        )
        db.session.add(private)
        db.session.commit()
        ids = {"owner": owner.id, "other": other.id, "private": private.id}
    return app, ids


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def assignment_body(**overrides):
    return {
        "title": "API project",
        "course": "CS 410",
        "deadline": "2026-08-15T17:00:00+00:00",
        "difficulty": 4,
        "estimated_minutes": 120,
        "course_impact": 35,
        "progress": 10,
        "completed": False,
        "notes": "Created through API v1.",
        **overrides,
    }


def test_authentication_error_uses_standard_shape(api_setup):
    app, _ = api_setup
    response = app.test_client().get("/api/v1/assignments")
    assert response.status_code == 401
    assert response.json == {
        "error": {
            "code": "authentication_required",
            "message": "Authentication is required.",
        }
    }


def test_assignment_crud_success(api_setup):
    app, ids = api_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    created = client.post("/api/v1/assignments", json=assignment_body())
    assert created.status_code == 201
    assignment_id = created.json["data"]["id"]
    assert created.json["data"]["title"] == "API project"

    collection = client.get("/api/v1/assignments")
    assert collection.status_code == 200
    assert collection.json["meta"]["count"] == 1

    detail = client.get(f"/api/v1/assignments/{assignment_id}")
    assert detail.json["data"]["course"] == "CS 410"

    updated = client.patch(
        f"/api/v1/assignments/{assignment_id}",
        json={"progress": 65, "title": "Updated API project"},
    )
    assert updated.status_code == 200
    assert updated.json["data"]["progress"] == 65
    assert updated.json["data"]["title"] == "Updated API project"

    deleted = client.delete(f"/api/v1/assignments/{assignment_id}")
    assert deleted.status_code == 200
    assert deleted.json["data"] == {"id": assignment_id, "deleted": True}
    assert client.get(f"/api/v1/assignments/{assignment_id}").status_code == 404


def test_assignment_validation_errors_are_consistent(api_setup):
    app, ids = api_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    response = client.post(
        "/api/v1/assignments",
        json=assignment_body(title="", difficulty=9, deadline="invalid"),
    )
    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation_error"
    assert set(response.json["error"]["fields"]) >= {"title", "difficulty", "deadline"}
    invalid_json = client.post(
        "/api/v1/assignments",
        data="not-json",
        content_type="application/json",
    )
    assert invalid_json.status_code == 400
    assert invalid_json.json["error"]["code"] == "invalid_json"


def test_assignment_ownership_is_enforced(api_setup):
    app, ids = api_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    for method in (client.get, client.patch, client.delete):
        kwargs = {"json": {"title": "stolen"}} if method == client.patch else {}
        response = method(f"/api/v1/assignments/{ids['private']}", **kwargs)
        assert response.status_code == 404
        assert response.json["error"]["code"] == "not_found"


def test_priority_explanation_endpoint(api_setup):
    app, ids = api_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    assignment_id = client.post("/api/v1/assignments", json=assignment_body()).json["data"]["id"]
    response = client.get(f"/api/v1/assignments/{assignment_id}/priority-explanation")
    assert response.status_code == 200
    assert 0 <= response.json["data"]["final_score"] <= 100
    assert len(response.json["data"]["factors"]) == 5
    assert response.json["data"]["summary"]


def test_focus_session_lifecycle_and_failures(api_setup):
    app, ids = api_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    assignment_id = client.post("/api/v1/assignments", json=assignment_body()).json["data"]["id"]
    invalid = client.post("/api/v1/focus-sessions", json={"assignment_id": assignment_id, "planned_minutes": 0})
    assert invalid.status_code == 422
    assert invalid.json["error"]["code"] == "validation_error"
    assert "planned_minutes" in invalid.json["error"]["fields"]

    started = client.post(
        "/api/v1/focus-sessions",
        json={"assignment_id": assignment_id, "planned_minutes": 25},
    )
    assert started.status_code == 201
    focus_id = started.json["data"]["id"]
    assert client.get("/api/v1/focus-sessions/active").json["data"]["id"] == focus_id
    assert client.post(f"/api/v1/focus-sessions/{focus_id}/pause").json["data"]["status"] == "paused"
    assert client.post(f"/api/v1/focus-sessions/{focus_id}/resume").json["data"]["status"] == "running"
    ended = client.post(f"/api/v1/focus-sessions/{focus_id}/end", json={"reason": "user_ended"})
    assert ended.json["data"]["status"] == "ended"
    assert client.get("/api/v1/focus-sessions/active").json["data"] is None
    assert client.get("/api/v1/focus-sessions").json["meta"]["count"] == 1


def test_focus_session_ownership_is_enforced(api_setup):
    app, ids = api_setup
    other = app.test_client()
    sign_in(other, ids["other"])
    started = other.post(
        "/api/v1/focus-sessions",
        json={"assignment_id": ids["private"], "planned_minutes": 20},
    )
    focus_id = started.json["data"]["id"]
    owner = app.test_client()
    sign_in(owner, ids["owner"])
    response = owner.post(f"/api/v1/focus-sessions/{focus_id}/pause")
    assert response.status_code == 404


def test_integration_connect_status_sync_and_disconnect(api_setup):
    app, ids = api_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    initial = client.get("/api/v1/integrations/google_calendar/status")
    assert initial.json["data"]["display_status"] == "Disconnected"

    connecting = client.post("/api/v1/integrations/google_calendar/connect")
    assert connecting.status_code == 202
    assert connecting.json["data"]["status"] == "connecting"
    assert connecting.json["data"]["authorization_url"].endswith("/integrations/google-calendar/demo-consent")

    with client.session_transaction() as session:
        state = session["google_oauth_attempt"]["state"]
    client.post(
        "/integrations/google-calendar/demo-callback",
        data={"state": state, "decision": "approve"},
    )
    synced = client.post("/api/v1/integrations/google_calendar/sync")
    assert synced.status_code == 200
    assert synced.json["data"]["integration"]["display_status"] == "Synced"

    disconnected = client.post("/api/v1/integrations/google_calendar/disconnect")
    assert disconnected.status_code == 200
    assert disconnected.json["data"]["status"] == "disconnected"
    assert client.get("/api/v1/integrations/google_calendar/status").json["data"]["display_status"] == "Disconnected"


def test_integration_provider_validation_and_notion_connect(api_setup):
    app, ids = api_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    missing = client.get("/api/v1/integrations/unknown/status")
    assert missing.status_code == 404
    notion = client.post("/api/v1/integrations/notion/connect")
    assert notion.status_code == 202
    assert notion.json["data"]["authorization_url"].endswith("/integrations/notion/demo-consent")
    unsupported = client.post("/api/v1/integrations/notion/sync")
    assert unsupported.status_code == 405
    assert unsupported.json["error"]["code"] == "operation_not_supported"
