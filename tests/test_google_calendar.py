from datetime import date, datetime, time, timezone

import pytest

from planguard import create_app, db
from planguard.models import Assignment, IntegrationState, OAuthCredential, ScheduledFocusBlock, User, WeeklyAvailability
from planguard.services.calendar import calendar_conflicts_for_user
from planguard.services.scheduling import recommendation_for_assignment


class FakeGoogleClient:
    exchange_calls = []

    def build_authorization_url(self, state, force_consent=False):
        return f"https://accounts.example.test/authorize?state={state}"

    def exchange_code(self, code):
        self.exchange_calls.append(code)
        return {
            "access_token": "plain-access-token",
            "refresh_token": "plain-refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    def revoke_token(self, token):
        return None


@pytest.fixture
def live_calendar_setup(tmp_path):
    from cryptography.fernet import Fernet

    FakeGoogleClient.exchange_calls = []
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "live-calendar-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'live-calendar.db'}",
        "GOOGLE_CALENDAR_MODE": "live",
        "GOOGLE_CLIENT_ID": "test-client",
        "GOOGLE_CLIENT_SECRET": "test-secret",
        "GOOGLE_OAUTH_REDIRECT_URI": "https://example.test/integrations/google-calendar/callback",
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "GOOGLE_OAUTH_CLIENT": FakeGoogleClient(),
    })
    with app.app_context():
        user = User(email="live@example.com", display_name="Live Student")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    return app, user_id


@pytest.fixture
def calendar_setup(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "calendar-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'calendar.db'}",
        "GOOGLE_CALENDAR_MODE": "demo",
    })
    with app.app_context():
        user = User(email="calendar@example.com", display_name="Calendar Student")
        user.set_password("password123")
        other = User(email="other-calendar@example.com", display_name="Other Student")
        other.set_password("password123")
        db.session.add_all([user, other])
        db.session.flush()
        assignment = Assignment(
            user_id=user.id, title="Calendar-aware project", course="CS 450",
            deadline=datetime(2026, 8, 5, 17, tzinfo=timezone.utc),
            difficulty=4, estimated_minutes=180, course_weight=40, progress=0,
        )
        db.session.add_all([
            assignment,
            WeeklyAvailability(
                user_id=user.id, weekday=0, starts_at_time=time(9),
                ends_at_time=time(17), label="Demo day",
            ),
        ])
        db.session.commit()
        ids = {"user": user.id, "other": other.id, "assignment": assignment.id}
    return app, ids


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def connect_demo(client):
    response = client.post("/integrations/google-calendar/connect")
    assert response.status_code == 302
    consent = client.get(response.headers["Location"])
    assert b"No Google account or real calendar data" in consent.data
    with client.session_transaction() as session:
        state = session["google_oauth_attempt"]["state"]
    return client.post(
        "/integrations/google-calendar/demo-callback",
        data={"state": state, "decision": "approve"},
    )


def test_demo_connect_uses_state_and_creates_no_credentials(calendar_setup):
    app, ids = calendar_setup
    client = app.test_client()
    sign_in(client, ids["user"])
    assert connect_demo(client).status_code == 302
    with app.app_context():
        integration = db.session.scalar(
            db.select(IntegrationState).where(IntegrationState.user_id == ids["user"])
        )
        assert (integration.mode, integration.status) == ("demo", "connected")
        assert db.session.scalar(db.select(OAuthCredential)) is None
        assert all(item["title"] == "Busy" for item in integration.cached_payload["busy_periods"])


def test_invalid_state_is_rejected_and_cannot_connect(calendar_setup):
    app, ids = calendar_setup
    client = app.test_client()
    sign_in(client, ids["user"])
    client.post("/integrations/google-calendar/connect")
    response = client.post(
        "/integrations/google-calendar/demo-callback",
        data={"state": "incorrect", "decision": "approve"},
    )
    assert response.status_code == 400
    with app.app_context():
        assert db.session.scalar(db.select(IntegrationState)).status == "disconnected"


def test_demo_conflicts_change_recommendations(calendar_setup):
    app, ids = calendar_setup
    client = app.test_client()
    sign_in(client, ids["user"])
    connect_demo(client)
    with app.app_context():
        user = db.session.get(User, ids["user"])
        assignment = db.session.get(Assignment, ids["assignment"])
        conflicts = calendar_conflicts_for_user(user.id, date(2026, 8, 3), 1)
        result = recommendation_for_assignment(
            assignment, user, start_day=date(2026, 8, 3), days=1,
            calendar_conflicts=conflicts,
        )
        assert result.scheduled_minutes == 180
        assert all(
            not (block.starts_at < conflict.ends_at and block.ends_at > conflict.starts_at)
            for block in result.suggestions for conflict in conflicts
        )


def test_manual_block_cannot_overlap_demo_calendar(calendar_setup):
    app, ids = calendar_setup
    client = app.test_client()
    sign_in(client, ids["user"])
    connect_demo(client)
    response = client.post(
        f"/assignments/{ids['assignment']}/schedule",
        data={"action": "adjust", "starts_at": "2026-08-03T10:15", "planned_minutes": "30"},
        follow_redirects=True,
    )
    assert b"overlaps a busy period" in response.data
    with app.app_context():
        assert db.session.scalar(
            db.select(ScheduledFocusBlock).where(ScheduledFocusBlock.status == "scheduled")
        ) is None


def test_disconnect_clears_conflicts_but_keeps_assignments(calendar_setup):
    app, ids = calendar_setup
    client = app.test_client()
    sign_in(client, ids["user"])
    connect_demo(client)
    response = client.post("/integrations/google-calendar/disconnect", follow_redirects=True)
    assert b"Calendar disconnected" in response.data
    with app.app_context():
        integration = db.session.scalar(db.select(IntegrationState))
        assert integration.status == "disconnected"
        assert integration.cached_payload is None
        assert db.session.get(Assignment, ids["assignment"]) is not None
        assert calendar_conflicts_for_user(ids["user"], date(2026, 8, 3), 1) == []


def test_user_cannot_disconnect_another_users_calendar(calendar_setup):
    app, ids = calendar_setup
    with app.app_context():
        db.session.add(IntegrationState(
            user_id=ids["other"], provider="google_calendar", mode="demo",
            status="connected", cached_payload={"busy_periods": []},
        ))
        db.session.commit()
    client = app.test_client()
    sign_in(client, ids["user"])
    client.post("/integrations/google-calendar/disconnect")
    with app.app_context():
        other = db.session.scalar(
            db.select(IntegrationState).where(IntegrationState.user_id == ids["other"])
        )
        assert other.status == "connected"


def test_dashboard_labels_demo_connection_honestly(calendar_setup):
    app, ids = calendar_setup
    client = app.test_client()
    sign_in(client, ids["user"])
    connect_demo(client)
    response = client.get("/dashboard")
    assert b"Demo" in response.data
    assert b"No Google account data is accessed" in response.data


def test_mocked_live_callback_encrypts_tokens(live_calendar_setup):
    app, user_id = live_calendar_setup
    client = app.test_client()
    sign_in(client, user_id)
    started = client.post("/integrations/google-calendar/connect")
    assert started.status_code == 302
    with client.session_transaction() as session:
        state = session["google_oauth_attempt"]["state"]
    response = client.get(
        "/integrations/google-calendar/callback",
        query_string={"state": state, "code": "authorization-code"},
    )
    assert response.status_code == 302
    with app.app_context():
        integration = db.session.scalar(db.select(IntegrationState))
        credential = db.session.scalar(db.select(OAuthCredential))
        assert integration.status == "connected"
        assert credential.encrypted_access_token != "plain-access-token"
        assert credential.encrypted_refresh_token != "plain-refresh-token"
        assert "plain-access-token" not in str(integration.cached_payload)


def test_provider_denial_does_not_exchange_code(live_calendar_setup):
    app, user_id = live_calendar_setup
    client = app.test_client()
    sign_in(client, user_id)
    client.post("/integrations/google-calendar/connect")
    with client.session_transaction() as session:
        state = session["google_oauth_attempt"]["state"]
    response = client.get(
        "/integrations/google-calendar/callback",
        query_string={
            "state": state,
            "error": "access_denied",
            "error_description": "raw provider detail must not render",
        },
        follow_redirects=True,
    )
    assert FakeGoogleClient.exchange_calls == []
    assert b"raw provider detail" not in response.data


def test_live_callback_state_is_single_use(live_calendar_setup):
    app, user_id = live_calendar_setup
    client = app.test_client()
    sign_in(client, user_id)
    client.post("/integrations/google-calendar/connect")
    with client.session_transaction() as session:
        state = session["google_oauth_attempt"]["state"]
    first = client.get(
        "/integrations/google-calendar/callback",
        query_string={"state": state, "code": "authorization-code"},
    )
    replay = client.get(
        "/integrations/google-calendar/callback",
        query_string={"state": state, "code": "authorization-code"},
    )
    assert first.status_code == 302
    assert replay.status_code == 400
    assert FakeGoogleClient.exchange_calls == ["authorization-code"]
    with app.app_context():
        assert db.session.scalar(db.select(IntegrationState)).status == "connected"
