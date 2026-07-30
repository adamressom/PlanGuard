from datetime import datetime, timezone

import pytest

from planguard import create_app, db
from planguard.models import IntegrationState, User


@pytest.fixture
def status_setup(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "status-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'status.db'}",
        "GOOGLE_CALENDAR_MODE": "demo",
        "NOTION_MODE": "demo",
    })
    with app.app_context():
        user = User(email="status@example.com", display_name="Status Student")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    return app, user_id


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def add_google_integration(app, user_id, **values):
    with app.app_context():
        integration = IntegrationState(
            user_id=user_id,
            provider="google_calendar",
            mode="live",
            status=values.pop("status", "connected"),
            sync_status=values.pop("sync_status", "never"),
            **values,
        )
        db.session.add(integration)
        db.session.commit()
        return integration.id


def test_disconnected_provider_status_truthfully_requests_connect(status_setup):
    app, user_id = status_setup
    client = app.test_client()
    sign_in(client, user_id)
    response = client.get("/api/integrations/google_calendar/status")
    assert response.status_code == 200
    assert response.json["display_status"] == "Disconnected"
    assert response.json["next_action"] == "Connect"
    dashboard = client.get("/dashboard")
    assert b"Connect demo calendar" in dashboard.data


def test_syncing_status_is_visible(status_setup):
    app, user_id = status_setup
    add_google_integration(app, user_id, sync_status="syncing")
    client = app.test_client()
    sign_in(client, user_id)
    response = client.get("/api/integrations/google_calendar/status")
    assert response.json["display_status"] == "Syncing"
    assert b"Syncing" in client.get("/dashboard").data


def test_synced_appears_only_after_success_with_timestamp(status_setup):
    app, user_id = status_setup
    synced_at = datetime(2026, 7, 29, 14, 30, tzinfo=timezone.utc)
    integration_id = add_google_integration(
        app,
        user_id,
        sync_status="never",
    )
    client = app.test_client()
    sign_in(client, user_id)
    before = client.get(f"/api/integrations/{integration_id}")
    assert before.json["display_status"] == "Connected"
    assert before.json["last_successful_sync_at"] is None
    with app.app_context():
        integration = db.session.get(IntegrationState, integration_id)
        integration.sync_status = "live"
        integration.last_synced_at = synced_at
        db.session.commit()
    after = client.get(f"/api/integrations/{integration_id}")
    assert after.json["display_status"] == "Synced"
    assert after.json["last_successful_sync_at"] is not None
    dashboard = client.get("/dashboard")
    assert b"Synced" in dashboard.data
    assert b"Last successful sync" in dashboard.data


def test_cached_fallback_and_retry_action_are_visible(status_setup):
    app, user_id = status_setup
    add_google_integration(
        app,
        user_id,
        sync_status="cached",
        last_synced_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
        last_error_code="provider_unavailable",
    )
    client = app.test_client()
    sign_in(client, user_id)
    status = client.get("/api/integrations/google_calendar/status").json
    assert status["display_status"] == "Using cached data"
    assert status["next_action"] == "Retry sync"
    dashboard = client.get("/dashboard")
    assert b"Using cached data" in dashboard.data
    assert b"last complete calendar sync" in dashboard.data


def test_error_has_useful_next_action(status_setup):
    app, user_id = status_setup
    add_google_integration(
        app,
        user_id,
        sync_status="error",
        last_error_code="permission_denied",
    )
    client = app.test_client()
    sign_in(client, user_id)
    status = client.get("/api/integrations/google_calendar/status").json
    assert status["display_status"] == "Error"
    assert status["next_action"] == "Retry or reconnect"
    dashboard = client.get("/dashboard")
    assert b"no usable cache" in dashboard.data
    assert b"Sync calendar" in dashboard.data


def test_clients_cannot_forge_integration_status(status_setup):
    app, user_id = status_setup
    integration_id = add_google_integration(app, user_id, status="disconnected")
    client = app.test_client()
    sign_in(client, user_id)
    response = client.patch(
        f"/api/integrations/{integration_id}",
        json={"status": "connected"},
    )
    assert response.status_code == 405
    with app.app_context():
        assert db.session.get(IntegrationState, integration_id).status == "disconnected"
