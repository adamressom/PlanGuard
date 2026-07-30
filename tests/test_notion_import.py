from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

from planguard import create_app, db
from planguard.models import Assignment, IntegrationState, NotionImportSource, OAuthCredential, User


MAPPING = {
    "title": "Assignment",
    "deadline": "Due",
    "course": "Course",
    "difficulty": "Difficulty",
    "estimated_minutes": "Estimate",
    "course_weight": "",
    "progress": "",
    "completed": "Done",
    "notes": "Notes",
}


@pytest.fixture
def notion_setup(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "notion-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'notion.db'}",
        "NOTION_MODE": "demo",
    })
    with app.app_context():
        user = User(email="notion@example.com", display_name="Notion Student")
        user.set_password("password123")
        other = User(email="other-notion@example.com", display_name="Other Student")
        other.set_password("password123")
        db.session.add_all([user, other])
        db.session.commit()
        ids = {"user": user.id, "other": other.id}
    return app, ids


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def connect_demo(client):
    started = client.post("/integrations/notion/connect")
    assert started.status_code == 302
    consent = client.get(started.headers["Location"])
    assert b"No Notion account or workspace data" in consent.data
    with client.session_transaction() as session:
        state = session["notion_oauth_attempt"]["state"]
    return client.post(
        "/integrations/notion/demo-callback",
        data={"state": state, "decision": "approve"},
    )


def select_demo_source(client):
    response = client.post(
        "/integrations/notion/sources",
        data={"source_id": "demo-coursework-source"},
    )
    assert response.status_code == 302


def test_demo_connect_select_map_preview_and_import(notion_setup):
    app, ids = notion_setup
    client = app.test_client()
    sign_in(client, ids["user"])
    assert connect_demo(client).status_code == 302
    sources = client.get("/integrations/notion/sources")
    assert b"Coursework" in sources.data
    select_demo_source(client)
    preview = client.post("/integrations/notion/mapping", data={**MAPPING, "action": "preview"})
    assert preview.status_code == 200
    assert b"Ready to import" in preview.data
    assert b"Calculus problem set" in preview.data
    imported = client.post(
        "/integrations/notion/mapping",
        data={**MAPPING, "action": "import"},
        follow_redirects=True,
    )
    assert b"Imported 3 assignments" in imported.data
    with app.app_context():
        assignments = db.session.scalars(
            db.select(Assignment).where(Assignment.user_id == ids["user"])
        ).all()
        assert len(assignments) == 3
        assert all(item.provider == "notion" for item in assignments)
        assert all(item.provider_id.startswith("demo-notion-") for item in assignments)
        assert db.session.scalar(db.select(OAuthCredential)) is None
        notion_integration = db.session.scalar(
            db.select(IntegrationState).where(IntegrationState.provider == "notion")
        )
        assert notion_integration.sync_status == "live"
        assert notion_integration.last_synced_at is not None


def test_reimport_skips_and_reports_existing_provider_ids(notion_setup):
    app, ids = notion_setup
    client = app.test_client()
    sign_in(client, ids["user"])
    connect_demo(client)
    select_demo_source(client)
    client.post("/integrations/notion/mapping", data={**MAPPING, "action": "import"})
    repeated = client.post(
        "/integrations/notion/mapping",
        data={**MAPPING, "action": "import"},
        follow_redirects=True,
    )
    assert b"0 assignments; 3 already imported" in repeated.data
    with app.app_context():
        assert db.session.scalar(
            db.select(db.func.count(Assignment.id)).where(Assignment.user_id == ids["user"])
        ) == 3


def test_imported_assignments_belong_only_to_signed_in_user(notion_setup):
    app, ids = notion_setup
    client = app.test_client()
    sign_in(client, ids["user"])
    connect_demo(client)
    select_demo_source(client)
    client.post("/integrations/notion/mapping", data={**MAPPING, "action": "import"})
    with app.app_context():
        assert db.session.scalar(
            db.select(db.func.count(Assignment.id)).where(Assignment.user_id == ids["other"])
        ) == 0


def test_invalid_demo_oauth_state_is_rejected(notion_setup):
    app, ids = notion_setup
    client = app.test_client()
    sign_in(client, ids["user"])
    client.post("/integrations/notion/connect")
    response = client.post(
        "/integrations/notion/demo-callback",
        data={"state": "wrong", "decision": "approve"},
    )
    assert response.status_code == 400
    with app.app_context():
        assert db.session.scalar(db.select(IntegrationState)).status == "disconnected"


def test_disconnect_clears_credentials_and_source_but_keeps_imports(notion_setup):
    app, ids = notion_setup
    client = app.test_client()
    sign_in(client, ids["user"])
    connect_demo(client)
    select_demo_source(client)
    client.post("/integrations/notion/mapping", data={**MAPPING, "action": "import"})
    response = client.post("/integrations/notion/disconnect", follow_redirects=True)
    assert b"Notion disconnected" in response.data
    with app.app_context():
        integration = db.session.scalar(db.select(IntegrationState))
        assert integration.status == "disconnected"
        assert db.session.scalar(db.select(NotionImportSource)) is None
        assert db.session.scalar(db.select(db.func.count(Assignment.id))) == 3


class FakeLiveNotionClient:
    exchange_calls = []

    def build_authorization_url(self, state):
        return f"https://notion.example.test/authorize?state={state}"

    def exchange_code(self, code):
        self.exchange_calls.append(code)
        return {
            "access_token": "plain-notion-access",
            "refresh_token": "plain-notion-refresh",
            "bot_id": "bot-123",
            "workspace_id": "workspace-123",
            "workspace_name": "Student workspace",
            "token_type": "bearer",
        }


@pytest.fixture
def live_notion_setup(tmp_path):
    FakeLiveNotionClient.exchange_calls = []
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "live-notion-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'live-notion.db'}",
        "NOTION_MODE": "live",
        "NOTION_CLIENT_ID": "client-id",
        "NOTION_CLIENT_SECRET": "client-secret",
        "NOTION_OAUTH_REDIRECT_URI": "https://example.test/integrations/notion/callback",
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "NOTION_CLIENT": FakeLiveNotionClient(),
    })
    with app.app_context():
        user = User(email="live-notion@example.com", display_name="Live Notion")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    return app, user_id


def test_mocked_live_oauth_encrypts_tokens_and_validates_state(live_notion_setup):
    app, user_id = live_notion_setup
    client = app.test_client()
    sign_in(client, user_id)
    started = client.post("/integrations/notion/connect")
    with client.session_transaction() as session:
        state = session["notion_oauth_attempt"]["state"]
    callback = client.get(
        "/integrations/notion/callback",
        query_string={"state": state, "code": "notion-code"},
    )
    assert callback.status_code == 302
    with app.app_context():
        integration = db.session.scalar(db.select(IntegrationState))
        credential = db.session.scalar(db.select(OAuthCredential))
        assert integration.status == "connected"
        assert integration.provider_account_id == "bot-123"
        assert credential.encrypted_access_token != "plain-notion-access"
        assert credential.encrypted_refresh_token != "plain-notion-refresh"
        assert "plain-notion-access" not in str(integration.cached_payload)
    replay = client.get(
        "/integrations/notion/callback",
        query_string={"state": state, "code": "notion-code"},
    )
    assert replay.status_code == 400
    assert FakeLiveNotionClient.exchange_calls == ["notion-code"]
