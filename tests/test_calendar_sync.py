from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from planguard import create_app, db
from planguard.models import IntegrationState, OAuthCredential, User
from planguard.services.calendar import (
    CACHE_VERSION,
    CalendarProviderError,
    encrypt_token,
    sync_google_calendar,
    sync_range,
)


FIXED_NOW = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)


class FakeCalendarApi:
    def __init__(self, calendar_pages=None, event_pages=None, calendar_failures=None):
        self.calendar_pages = calendar_pages or [{
            "items": [{"id": "primary", "primary": True, "selected": True, "accessRole": "owner"}]
        }]
        self.event_pages = event_pages or {"primary": [{"items": []}]}
        self.calendar_failures = list(calendar_failures or [])
        self.calendar_calls = 0
        self.event_calls = []

    def list_calendar_page(self, access_token, page_token=None):
        self.calendar_calls += 1
        if self.calendar_failures:
            failure = self.calendar_failures.pop(0)
            if failure:
                raise failure
        index = int(page_token or 0)
        payload = dict(self.calendar_pages[index])
        if index + 1 < len(self.calendar_pages):
            payload["nextPageToken"] = str(index + 1)
        return payload

    def list_event_page(self, access_token, calendar_id, range_start, range_end, page_token=None):
        self.event_calls.append((calendar_id, page_token))
        pages = self.event_pages[calendar_id]
        index = int(page_token or 0)
        payload = pages[index]
        if isinstance(payload, Exception):
            raise payload
        payload = dict(payload)
        if index + 1 < len(pages):
            payload["nextPageToken"] = str(index + 1)
        return payload


@pytest.fixture
def sync_setup(tmp_path):
    key = Fernet.generate_key().decode()
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "sync-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'sync.db'}",
        "GOOGLE_CALENDAR_MODE": "live",
        "GOOGLE_CLIENT_ID": "client",
        "GOOGLE_CLIENT_SECRET": "secret",
        "GOOGLE_OAUTH_REDIRECT_URI": "https://example.test/callback",
        "TOKEN_ENCRYPTION_KEY": key,
    })
    with app.app_context():
        user = User(email="sync@example.com", display_name="Sync Student")
        user.set_password("password123")
        integration = IntegrationState(
            user_id=1,
            provider="google_calendar",
            mode="live",
            status="connected",
        )
        db.session.add(user)
        db.session.flush()
        integration.user_id = user.id
        db.session.add(integration)
        db.session.flush()
        db.session.add(OAuthCredential(
            integration_id=integration.id,
            encrypted_access_token=encrypt_token("access-token"),
            encrypted_refresh_token=encrypt_token("refresh-token"),
            access_token_expires_at=FIXED_NOW + timedelta(days=1),
        ))
        db.session.commit()
        ids = {"user": user.id, "integration": integration.id}
    return app, ids


def _event(start, end, **overrides):
    event = {
        "status": "confirmed",
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    event.update(overrides)
    return event


def test_live_sync_follows_pages_filters_events_and_caches_busy_ranges(sync_setup):
    app, ids = sync_setup
    api = FakeCalendarApi(
        calendar_pages=[
            {"items": [
                {"id": "primary", "primary": True, "selected": True, "accessRole": "owner"},
                {"id": "hidden", "selected": False, "accessRole": "reader"},
            ]},
            {"items": [{"id": "school", "selected": True, "accessRole": "reader"}]},
        ],
        event_pages={
            "primary": [
                {"items": [
                    _event("2026-07-29T10:00:00-04:00", "2026-07-29T11:00:00-04:00"),
                    _event("2026-07-29T11:00:00-04:00", "2026-07-29T11:30:00-04:00"),
                    _event("2026-07-29T12:00:00-04:00", "2026-07-29T13:00:00-04:00", transparency="transparent"),
                ]},
                {"items": [
                    _event(
                        "2026-07-29T13:00:00-04:00",
                        "2026-07-29T14:00:00-04:00",
                        attendees=[{"self": True, "responseStatus": "declined"}],
                    )
                ]},
            ],
            "school": [{"items": [
                {"status": "confirmed", "start": {"date": "2026-07-30"}, "end": {"date": "2026-07-31"}},
                _event("2026-07-30T15:00:00-04:00", "2026-07-30T16:00:00-04:00", eventType="workingLocation"),
            ]}],
        },
    )
    app.config["GOOGLE_CALENDAR_API_CLIENT"] = api
    with app.app_context():
        integration = db.session.get(IntegrationState, ids["integration"])
        result = sync_google_calendar(integration, now=FIXED_NOW, sleeper=lambda _: None, jitter=lambda: 0)
        assert result.ok is True
        assert result.source == "live"
        assert len(result.busy_periods) == 2
        assert result.busy_periods[0].starts_at.isoformat() == "2026-07-29T14:00:00+00:00"
        assert result.busy_periods[0].ends_at.isoformat() == "2026-07-29T15:30:00+00:00"
        assert integration.cached_payload["version"] == CACHE_VERSION
        assert integration.cached_payload["busy_periods"][0]["title"] == "Busy"
        assert integration.sync_status == "live"
        assert integration.last_synced_at is not None
        assert {call[0] for call in api.event_calls} == {"primary", "school"}


def test_transient_failure_retries_with_bounded_backoff(sync_setup):
    app, ids = sync_setup
    api = FakeCalendarApi(calendar_failures=[
        CalendarProviderError("provider_unavailable", temporary=True),
        CalendarProviderError("provider_unavailable", temporary=True),
        None,
    ])
    app.config["GOOGLE_CALENDAR_API_CLIENT"] = api
    sleeps = []
    with app.app_context():
        integration = db.session.get(IntegrationState, ids["integration"])
        result = sync_google_calendar(integration, now=FIXED_NOW, sleeper=sleeps.append, jitter=lambda: 0)
        assert result.ok is True
        assert api.calendar_calls == 3
        assert sleeps == [0.5, 1.5]
        assert integration.retry_count == 2


def test_failed_partial_sync_preserves_complete_cache_and_uses_fallback(sync_setup):
    app, ids = sync_setup
    api = FakeCalendarApi(event_pages={
        "primary": [
            {"items": [_event("2026-07-29T09:00:00-04:00", "2026-07-29T10:00:00-04:00")]},
            CalendarProviderError("provider_unavailable", temporary=True),
        ]
    })
    app.config["GOOGLE_CALENDAR_API_CLIENT"] = api
    with app.app_context():
        integration = db.session.get(IntegrationState, ids["integration"])
        range_start, range_end = sync_range(FIXED_NOW)
        integration.cached_payload = {
            "version": CACHE_VERSION,
            "timezone": "America/New_York",
            "range_start": range_start.isoformat(),
            "range_end": range_end.isoformat(),
            "busy_periods": [{
                "title": "Busy",
                "starts_at": "2026-07-29T18:00:00+00:00",
                "ends_at": "2026-07-29T19:00:00+00:00",
            }],
        }
        integration.last_synced_at = FIXED_NOW - timedelta(hours=1)
        original_cache = dict(integration.cached_payload)
        db.session.commit()
        result = sync_google_calendar(integration, now=FIXED_NOW, sleeper=lambda _: None, jitter=lambda: 0)
        assert result.ok is False
        assert result.source == "cache"
        assert integration.sync_status == "cached"
        assert integration.status == "connected"
        assert integration.cached_payload == original_cache
        assert len(result.busy_periods) == 1
        assert result.busy_periods[0].starts_at.isoformat() == "2026-07-29T18:00:00+00:00"


def test_failure_without_covered_cache_reports_error(sync_setup):
    app, ids = sync_setup
    api = FakeCalendarApi(calendar_failures=[
        CalendarProviderError("provider_timeout", temporary=True),
        CalendarProviderError("provider_timeout", temporary=True),
        CalendarProviderError("provider_timeout", temporary=True),
    ])
    app.config["GOOGLE_CALENDAR_API_CLIENT"] = api
    with app.app_context():
        integration = db.session.get(IntegrationState, ids["integration"])
        result = sync_google_calendar(integration, now=FIXED_NOW, sleeper=lambda _: None, jitter=lambda: 0)
        assert result.ok is False
        assert result.source == "error"
        assert integration.sync_status == "error"
        assert integration.cached_payload is None


def test_successful_empty_sync_replaces_old_cache(sync_setup):
    app, ids = sync_setup
    api = FakeCalendarApi()
    app.config["GOOGLE_CALENDAR_API_CLIENT"] = api
    with app.app_context():
        integration = db.session.get(IntegrationState, ids["integration"])
        integration.cached_payload = {"version": CACHE_VERSION, "busy_periods": [{"title": "Busy"}]}
        db.session.commit()
        result = sync_google_calendar(integration, now=FIXED_NOW, sleeper=lambda _: None, jitter=lambda: 0)
        assert result.ok is True
        assert integration.cached_payload["busy_periods"] == []
        assert integration.sync_status == "live"


def test_sync_endpoint_exposes_live_ui_state(sync_setup):
    app, ids = sync_setup
    app.config["GOOGLE_CALENDAR_API_CLIENT"] = FakeCalendarApi()
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = ids["user"]
    response = client.post("/integrations/google-calendar/sync", follow_redirects=True)
    assert response.status_code == 200
    assert b"Google Calendar data updated" in response.data
    assert b"Synced" in response.data
    with app.app_context():
        integration = db.session.get(IntegrationState, ids["integration"])
        assert integration.sync_status == "live"
        assert integration.last_sync_attempt_at is not None
