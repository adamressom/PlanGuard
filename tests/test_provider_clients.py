import io
import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError

import pytest

from planguard.integrations import notion
from planguard.integrations.base import CachedIntegration
from planguard.integrations.google_calendar import GoogleCalendarIntegration
from planguard.services import calendar


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


def http_error(status, payload, headers=None):
    return HTTPError(
        "https://provider.example",
        status,
        "provider error",
        headers or {},
        io.BytesIO(json.dumps(payload).encode()),
    )


def test_legacy_cached_integration_boundary_uses_cache_on_failure():
    assert CachedIntegration().fetch_with_fallback(["cached"]).source == "cache"
    result = GoogleCalendarIntegration().fetch_with_fallback(["cached"])
    assert result.ok is False
    assert result.data == ["cached"]
    assert result.source == "cache"


def test_google_oauth_client_builds_urls_and_posts_forms(app, monkeypatch):
    app.config.update({
        "GOOGLE_CLIENT_ID": "client-id",
        "GOOGLE_CLIENT_SECRET": "client-secret",
        "GOOGLE_OAUTH_REDIRECT_URI": "https://app.example/callback",
    })
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse({
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        })

    monkeypatch.setattr(calendar, "urlopen", fake_urlopen)
    with app.app_context():
        client = calendar.GoogleOAuthClient()
        authorization_url = client.build_authorization_url("state-value", force_consent=True)
        assert "state=state-value" in authorization_url
        assert "prompt=consent" in authorization_url
        assert client.exchange_code("code")["access_token"] == "access"
        assert client.refresh_access_token("refresh")["access_token"] == "access"
        client.revoke_token("access")
    assert len(requests) == 3
    assert all(request.get_method() == "POST" for request in requests)


@pytest.mark.parametrize(
    ("status", "payload", "expected", "temporary"),
    [
        (401, {}, "authentication_failed", False),
        (403, {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}, "rate_limited", True),
        (429, {}, "rate_limited", True),
        (404, {}, "calendar_not_found", True),
        (503, {}, "provider_unavailable", True),
        (403, {}, "permission_denied", False),
        (400, {}, "provider_rejected_request", False),
    ],
)
def test_google_calendar_client_maps_http_failures(
    app,
    monkeypatch,
    status,
    payload,
    expected,
    temporary,
):
    monkeypatch.setattr(
        calendar,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(http_error(status, payload)),
    )
    with app.app_context(), pytest.raises(calendar.CalendarProviderError) as raised:
        calendar.GoogleCalendarApiClient().list_calendar_page("access")
    assert raised.value.code == expected
    assert raised.value.temporary is temporary


def test_google_calendar_client_lists_calendars_and_events(app, monkeypatch):
    seen_urls = []

    def fake_urlopen(request, timeout):
        seen_urls.append(request.full_url)
        return FakeResponse({"items": []})

    monkeypatch.setattr(calendar, "urlopen", fake_urlopen)
    now = datetime.now(timezone.utc)
    with app.app_context():
        client = calendar.GoogleCalendarApiClient()
        assert client.list_calendar_page("access", "next") == {"items": []}
        assert client.list_event_page(
            "access",
            "calendar/id",
            now,
            now + timedelta(days=1),
            "next",
        ) == {"items": []}
    assert "pageToken=next" in seen_urls[0]
    assert "calendar%2Fid" in seen_urls[1]


def test_google_clients_map_network_and_invalid_json(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(
            calendar,
            "urlopen",
            lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
        )
        with pytest.raises(calendar.CalendarProviderError, match="provider_unavailable"):
            calendar.GoogleOAuthClient().exchange_code("code")
        with pytest.raises(calendar.CalendarProviderError, match="provider_timeout"):
            calendar.GoogleCalendarApiClient().list_calendar_page("access")

        monkeypatch.setattr(calendar, "urlopen", lambda *args, **kwargs: FakeResponse([]))
        with pytest.raises(calendar.CalendarProviderError, match="invalid_provider_response"):
            calendar.GoogleCalendarApiClient().list_calendar_page("access")


def test_notion_client_builds_oauth_and_api_requests(app, monkeypatch):
    app.config.update({
        "NOTION_CLIENT_ID": "notion-client",
        "NOTION_CLIENT_SECRET": "notion-secret",
        "NOTION_OAUTH_REDIRECT_URI": "https://app.example/notion/callback",
    })
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse({})

    monkeypatch.setattr(notion, "urlopen", fake_urlopen)
    with app.app_context():
        client = notion.NotionClient()
        assert "state=state-value" in client.build_authorization_url("state-value")
        client.exchange_code("code")
        client.refresh_access_token("refresh")
        client.revoke_token("access")
        client.search_source_page("access", "cursor")
        client.retrieve_source("access", "source")
        client.query_source_page("access", "source", "cursor")
    assert len(requests) == 6
    assert requests[0].headers["Authorization"].startswith("Basic ")
    assert requests[-1].headers["Authorization"] == "Bearer access"


@pytest.mark.parametrize(
    ("status", "payload", "expected", "temporary"),
    [
        (401, {"code": "provider_code"}, "unauthorized", False),
        (429, {"code": "rate_limited"}, "rate_limited", True),
        (503, {"code": "service_unavailable"}, "service_unavailable", True),
    ],
)
def test_notion_client_maps_http_failures(
    app,
    monkeypatch,
    status,
    payload,
    expected,
    temporary,
):
    monkeypatch.setattr(
        notion,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(http_error(status, payload)),
    )
    with app.app_context(), pytest.raises(notion.NotionProviderError) as raised:
        notion.NotionClient().retrieve_source("access", "source")
    assert raised.value.code == expected
    assert raised.value.temporary is temporary


def test_notion_client_maps_network_and_invalid_payload(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(
            notion,
            "urlopen",
            lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
        )
        with pytest.raises(notion.NotionProviderError, match="provider_unavailable"):
            notion.NotionClient().retrieve_source("access", "source")

        monkeypatch.setattr(notion, "urlopen", lambda *args, **kwargs: FakeResponse([]))
        with pytest.raises(notion.NotionProviderError, match="invalid_provider_response"):
            notion.NotionClient().retrieve_source("access", "source")
