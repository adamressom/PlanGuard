import json
import random
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app

from .. import db
from ..models import IntegrationState, OAuthCredential
from .scheduling import ScheduleConflict, aware_datetime

GOOGLE_PROVIDER = "google_calendar"
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
)
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOCATION_ENDPOINT = "https://oauth2.googleapis.com/revoke"
REFRESH_BUFFER = timedelta(minutes=5)
CACHE_VERSION = 1
CACHE_FRESHNESS = timedelta(minutes=15)
CALENDAR_API_ROOT = "https://www.googleapis.com/calendar/v3"
RETRY_DELAYS = (0.5, 1.5)
READER_ROLES = {"reader", "writer", "owner"}


class CalendarProviderError(RuntimeError):
    def __init__(self, code, temporary=False, retry_after=None):
        super().__init__(code)
        self.code = code
        self.temporary = temporary
        self.retry_after = retry_after


@dataclass(frozen=True)
class CalendarStatus:
    mode: str
    status: str
    connected: bool
    last_synced_at: datetime | None
    last_error_code: str | None
    busy_count: int = 0
    sync_status: str = "never"
    cache_is_stale: bool = False


@dataclass(frozen=True)
class CalendarSyncResult:
    ok: bool
    source: str
    busy_periods: list[ScheduleConflict]
    synced_at: datetime | None
    error_code: str | None = None


def google_integration_for_user(user_id, create=False):
    integration = db.session.scalar(
        db.select(IntegrationState).where(
            IntegrationState.user_id == user_id,
            IntegrationState.provider == GOOGLE_PROVIDER,
        )
    )
    if integration is None and create:
        integration = IntegrationState(
            user_id=user_id,
            provider=GOOGLE_PROVIDER,
            status="disconnected",
        )
        db.session.add(integration)
        db.session.flush()
    return integration


def calendar_status_for_user(user_id, start_day=None, days=7):
    mode = current_app.config["GOOGLE_CALENDAR_MODE"]
    integration = google_integration_for_user(user_id)
    connected = bool(integration and integration.status == "connected")
    busy_count = len(calendar_conflicts_for_user(user_id, start_day, days)) if connected else 0
    last_synced_at = integration.last_synced_at if integration else None
    last_synced_aware = aware_datetime(last_synced_at)
    return CalendarStatus(
        mode=integration.mode if integration and integration.mode else mode,
        status=integration.status if integration else "disconnected",
        connected=connected,
        last_synced_at=last_synced_at,
        last_error_code=integration.last_error_code if integration else None,
        busy_count=busy_count,
        sync_status=integration.sync_status if integration else "never",
        cache_is_stale=bool(
            last_synced_aware
            and datetime.now(timezone.utc) - last_synced_aware > CACHE_FRESHNESS
        ),
    )


def demo_busy_periods(start_day, days=7):
    periods = []
    for offset in range(days):
        current_day = start_day + timedelta(days=offset)
        for starts, ends in ((time(10), time(11)), (time(12, 30), time(13, 15)), (time(14), time(15, 30))):
            periods.append(ScheduleConflict(
                datetime.combine(current_day, starts, tzinfo=timezone.utc),
                datetime.combine(current_day, ends, tzinfo=timezone.utc),
                "Busy",
                GOOGLE_PROVIDER,
            ))
    return periods


def _cached_conflicts(integration, start_day, days):
    local_zone = _configured_timezone()
    range_start = datetime.combine(start_day, time.min, tzinfo=local_zone).astimezone(timezone.utc)
    range_end = datetime.combine(
        start_day + timedelta(days=days),
        time.min,
        tzinfo=local_zone,
    ).astimezone(timezone.utc)
    if not cache_covers(integration, range_start, range_end):
        return []
    conflicts = []
    payload = integration.cached_payload or {}
    if payload.get("version") not in (None, CACHE_VERSION):
        return []
    for item in payload.get("busy_periods", []):
        try:
            starts_at = aware_datetime(datetime.fromisoformat(item["starts_at"]))
            ends_at = aware_datetime(datetime.fromisoformat(item["ends_at"]))
        except (KeyError, TypeError, ValueError):
            continue
        if starts_at < range_end and ends_at > range_start:
            conflicts.append(ScheduleConflict(starts_at, ends_at, "Busy", GOOGLE_PROVIDER))
    return merge_busy_periods(conflicts)


def merge_busy_periods(conflicts):
    ordered = sorted(conflicts, key=lambda item: (item.starts_at, item.ends_at))
    merged = []
    for conflict in ordered:
        if not merged or aware_datetime(conflict.starts_at) > aware_datetime(merged[-1].ends_at):
            merged.append(conflict)
            continue
        previous = merged[-1]
        merged[-1] = ScheduleConflict(
            previous.starts_at,
            max(aware_datetime(previous.ends_at), aware_datetime(conflict.ends_at)),
            "Busy",
            GOOGLE_PROVIDER,
        )
    return merged


def calendar_conflicts_for_user(user_id, start_day=None, days=7):
    start_day = start_day or datetime.now(timezone.utc).date()
    integration = google_integration_for_user(user_id)
    if integration is None or integration.status != "connected":
        return []
    if integration.mode == "demo":
        return demo_busy_periods(start_day, days)
    return _cached_conflicts(integration, start_day, days)


def cache_busy_periods(integration, conflicts, range_start=None, range_end=None, timezone_name=None):
    now = datetime.now(timezone.utc)
    if range_start is None:
        range_start = now
    if range_end is None:
        range_end = range_start + timedelta(days=14)
    integration.cached_payload = {
        "version": CACHE_VERSION,
        "timezone": timezone_name or current_app.config["DEFAULT_TIMEZONE"],
        "range_start": aware_datetime(range_start).isoformat(),
        "range_end": aware_datetime(range_end).isoformat(),
        "busy_periods": [
            {
                "title": "Busy",
                "starts_at": aware_datetime(item.starts_at).isoformat(),
                "ends_at": aware_datetime(item.ends_at).isoformat(),
            }
            for item in merge_busy_periods(conflicts)
        ]
    }
    integration.last_synced_at = now
    integration.sync_status = "live"
    integration.last_error_code = None
    integration.retry_count = 0


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise CalendarProviderError("encryption_unavailable") from exc
    key = current_app.config.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise CalendarProviderError("encryption_not_configured")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (TypeError, ValueError) as exc:
        raise CalendarProviderError("encryption_key_invalid") from exc


def encrypt_token(token):
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(token):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception as exc:
        raise CalendarProviderError("credential_decryption_failed") from exc


class GoogleOAuthClient:
    def build_authorization_url(self, state, force_consent=False):
        params = {
            "client_id": current_app.config["GOOGLE_CLIENT_ID"],
            "redirect_uri": current_app.config["GOOGLE_OAUTH_REDIRECT_URI"],
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "state": state,
        }
        if force_consent:
            params["prompt"] = "consent"
        return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    def _post_form(self, url, data):
        request = Request(
            url,
            data=urlencode(data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                body = response.read().decode()
                return json.loads(body) if body else {}
        except HTTPError as exc:
            code = "provider_rejected_request"
            try:
                code = json.loads(exc.read().decode()).get("error", code)
            except (ValueError, AttributeError):
                pass
            raise CalendarProviderError(code, temporary=exc.code >= 500) from exc
        except (URLError, TimeoutError, ValueError) as exc:
            raise CalendarProviderError("provider_unavailable", temporary=True) from exc

    def exchange_code(self, code):
        return self._post_form(TOKEN_ENDPOINT, {
            "code": code,
            "client_id": current_app.config["GOOGLE_CLIENT_ID"],
            "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": current_app.config["GOOGLE_OAUTH_REDIRECT_URI"],
            "grant_type": "authorization_code",
        })

    def refresh_access_token(self, refresh_token):
        return self._post_form(TOKEN_ENDPOINT, {
            "refresh_token": refresh_token,
            "client_id": current_app.config["GOOGLE_CLIENT_ID"],
            "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
            "grant_type": "refresh_token",
        })

    def revoke_token(self, token):
        self._post_form(REVOCATION_ENDPOINT, {"token": token})


def oauth_client():
    configured = current_app.config.get("GOOGLE_OAUTH_CLIENT")
    return configured() if isinstance(configured, type) else configured or GoogleOAuthClient()


def store_token_response(integration, payload):
    access_token = payload.get("access_token")
    expires_in = payload.get("expires_in")
    if not access_token or not isinstance(expires_in, (int, float)) or expires_in <= 0:
        raise CalendarProviderError("invalid_token_response")
    credential = integration.credential or OAuthCredential(integration=integration)
    if credential.id is None:
        db.session.add(credential)
    credential.encrypted_access_token = encrypt_token(access_token)
    refresh_token = payload.get("refresh_token")
    if refresh_token:
        credential.encrypted_refresh_token = encrypt_token(refresh_token)
    if not credential.encrypted_refresh_token:
        raise CalendarProviderError("refresh_token_missing")
    credential.access_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    credential.token_type = payload.get("token_type", "Bearer")
    credential.encryption_key_version = current_app.config["TOKEN_ENCRYPTION_KEY_VERSION"]
    integration.granted_scopes = str(payload.get("scope", " ".join(GOOGLE_SCOPES))).split()
    return credential


def valid_access_token(integration, force_refresh=False):
    credential = integration.credential
    if credential is None or not credential.encrypted_refresh_token:
        integration.status = "expired"
        integration.last_error_code = "refresh_token_missing"
        db.session.commit()
        raise CalendarProviderError("refresh_token_missing")
    expires_at = aware_datetime(credential.access_token_expires_at)
    if not force_refresh and credential.encrypted_access_token and expires_at:
        if expires_at > datetime.now(timezone.utc) + REFRESH_BUFFER:
            return decrypt_token(credential.encrypted_access_token)
    try:
        payload = oauth_client().refresh_access_token(decrypt_token(credential.encrypted_refresh_token))
        store_token_response(integration, payload)
        integration.status = "connected"
        integration.last_error_code = None
        db.session.commit()
        return decrypt_token(credential.encrypted_access_token)
    except CalendarProviderError as exc:
        db.session.rollback()
        integration = db.session.get(IntegrationState, integration.id)
        integration.last_error_code = exc.code
        integration.status = "error" if exc.temporary else "expired"
        integration.retry_count += 1
        db.session.commit()
        raise


def _configured_timezone():
    try:
        return ZoneInfo(current_app.config["DEFAULT_TIMEZONE"])
    except ZoneInfoNotFoundError:
        return timezone.utc


def sync_range(now=None, days=8):
    now = aware_datetime(now or datetime.now(timezone.utc))
    local_zone = _configured_timezone()
    local_today = now.astimezone(local_zone).date()
    local_start = datetime.combine(local_today, time.min, tzinfo=local_zone)
    local_end = datetime.combine(local_today + timedelta(days=days), time.min, tzinfo=local_zone)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def _event_declined(event):
    return any(
        attendee.get("self") is True and attendee.get("responseStatus") == "declined"
        for attendee in event.get("attendees", [])
        if isinstance(attendee, dict)
    )


def normalize_google_event(event, default_zone=None):
    if not isinstance(event, dict):
        return None
    if event.get("status") == "cancelled":
        return None
    if event.get("transparency") == "transparent":
        return None
    if event.get("eventType") == "workingLocation":
        return None
    if _event_declined(event):
        return None
    start_data = event.get("start") or {}
    end_data = event.get("end") or {}
    try:
        if start_data.get("dateTime") and end_data.get("dateTime"):
            starts_at = aware_datetime(datetime.fromisoformat(start_data["dateTime"].replace("Z", "+00:00")))
            ends_at = aware_datetime(datetime.fromisoformat(end_data["dateTime"].replace("Z", "+00:00")))
        elif start_data.get("date") and end_data.get("date"):
            zone = default_zone or _configured_timezone()
            starts_at = datetime.combine(date.fromisoformat(start_data["date"]), time.min, tzinfo=zone)
            ends_at = datetime.combine(date.fromisoformat(end_data["date"]), time.min, tzinfo=zone)
            starts_at = starts_at.astimezone(timezone.utc)
            ends_at = ends_at.astimezone(timezone.utc)
        else:
            return None
    except (TypeError, ValueError):
        return None
    if ends_at <= starts_at:
        return None
    return ScheduleConflict(starts_at, ends_at, "Busy", GOOGLE_PROVIDER)


class GoogleCalendarApiClient:
    def _get_json(self, path, access_token, params=None):
        url = f"{CALENDAR_API_ROOT}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, headers={"Authorization": f"Bearer {access_token}"})
        try:
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode())
        except HTTPError as exc:
            reason = ""
            try:
                error_payload = json.loads(exc.read().decode())
                errors = error_payload.get("error", {}).get("errors", [])
                reason = errors[0].get("reason", "") if errors else ""
            except (ValueError, AttributeError, IndexError):
                pass
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if exc.code == 401:
                raise CalendarProviderError("authentication_failed") from exc
            if exc.code == 403 and reason in {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}:
                raise CalendarProviderError("rate_limited", temporary=True, retry_after=retry_after) from exc
            if exc.code == 429:
                raise CalendarProviderError("rate_limited", temporary=True, retry_after=retry_after) from exc
            if exc.code == 404:
                raise CalendarProviderError("calendar_not_found", temporary=True) from exc
            if exc.code in {408, 500, 502, 503, 504}:
                raise CalendarProviderError("provider_unavailable", temporary=True, retry_after=retry_after) from exc
            if exc.code == 403:
                raise CalendarProviderError("permission_denied") from exc
            raise CalendarProviderError("provider_rejected_request") from exc
        except (URLError, TimeoutError) as exc:
            raise CalendarProviderError("provider_timeout", temporary=True) from exc
        except (UnicodeDecodeError, ValueError) as exc:
            raise CalendarProviderError("invalid_provider_response") from exc
        if not isinstance(payload, dict):
            raise CalendarProviderError("invalid_provider_response")
        return payload

    def list_calendar_page(self, access_token, page_token=None):
        params = {"maxResults": 250, "minAccessRole": "reader"}
        if page_token:
            params["pageToken"] = page_token
        return self._get_json("/users/me/calendarList", access_token, params)

    def list_event_page(self, access_token, calendar_id, range_start, range_end, page_token=None):
        params = {
            "singleEvents": "true",
            "showDeleted": "false",
            "orderBy": "startTime",
            "maxResults": 2500,
            "timeMin": aware_datetime(range_start).isoformat(),
            "timeMax": aware_datetime(range_end).isoformat(),
            "timeZone": current_app.config["DEFAULT_TIMEZONE"],
        }
        if page_token:
            params["pageToken"] = page_token
        return self._get_json(
            f"/calendars/{quote(str(calendar_id), safe='')}/events",
            access_token,
            params,
        )


def calendar_api_client():
    configured = current_app.config.get("GOOGLE_CALENDAR_API_CLIENT")
    return configured() if isinstance(configured, type) else configured or GoogleCalendarApiClient()


def _retry_delay(error, retry_index, jitter):
    if error.retry_after is not None:
        try:
            return min(max(float(error.retry_after), 0), 5)
        except (TypeError, ValueError):
            pass
    return RETRY_DELAYS[retry_index] + jitter()


def _request_with_retry(call, retry_counter, sleeper, jitter):
    for attempt in range(3):
        try:
            return call()
        except CalendarProviderError as exc:
            if not exc.temporary or attempt == 2:
                raise
            retry_counter[0] += 1
            sleeper(_retry_delay(exc, attempt, jitter))
    raise CalendarProviderError("provider_unavailable", temporary=True)


def _selected_calendars(client, access_token, retry_counter, sleeper, jitter):
    calendars = []
    page_token = None
    while True:
        payload = _request_with_retry(
            lambda token=page_token: client.list_calendar_page(access_token, token),
            retry_counter,
            sleeper,
            jitter,
        )
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise CalendarProviderError("invalid_provider_response")
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            selected = item.get("selected", item.get("primary", False))
            if selected and item.get("accessRole") in READER_ROLES:
                calendars.append(item)
        page_token = payload.get("nextPageToken")
        if not page_token:
            return calendars


def _calendar_events(client, access_token, calendar, range_start, range_end, retry_counter, sleeper, jitter):
    conflicts = []
    page_token = None
    while True:
        payload = _request_with_retry(
            lambda token=page_token: client.list_event_page(
                access_token,
                calendar["id"],
                range_start,
                range_end,
                token,
            ),
            retry_counter,
            sleeper,
            jitter,
        )
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise CalendarProviderError("invalid_provider_response")
        calendar_zone = calendar.get("timeZone")
        try:
            default_zone = ZoneInfo(calendar_zone) if calendar_zone else _configured_timezone()
        except ZoneInfoNotFoundError:
            default_zone = _configured_timezone()
        for event in items:
            conflict = normalize_google_event(event, default_zone)
            if conflict:
                conflicts.append(conflict)
        page_token = payload.get("nextPageToken")
        if not page_token:
            return conflicts


def cache_covers(integration, range_start, range_end):
    payload = integration.cached_payload or {}
    if payload.get("version") != CACHE_VERSION:
        return False
    try:
        cached_start = aware_datetime(datetime.fromisoformat(payload["range_start"]))
        cached_end = aware_datetime(datetime.fromisoformat(payload["range_end"]))
    except (KeyError, TypeError, ValueError):
        return False
    return cached_start <= aware_datetime(range_start) and cached_end >= aware_datetime(range_end)


def sync_google_calendar(integration, now=None, sleeper=None, jitter=None):
    sleeper = sleeper or time_module.sleep
    jitter = jitter or (lambda: random.uniform(0, 0.25))
    range_start, range_end = sync_range(now)
    integration.sync_status = "syncing"
    integration.last_sync_attempt_at = datetime.now(timezone.utc)
    integration.retry_count = 0
    integration.last_error_code = None
    db.session.commit()

    if integration.mode == "demo":
        periods = demo_busy_periods(range_start.date(), 8)
        cache_busy_periods(
            integration,
            periods,
            range_start,
            range_end,
            current_app.config["DEFAULT_TIMEZONE"],
        )
        db.session.commit()
        return CalendarSyncResult(True, "live", periods, integration.last_synced_at)

    retry_counter = [0]
    try:
        access_token = valid_access_token(integration)
        client = calendar_api_client()
        try:
            calendars = _selected_calendars(client, access_token, retry_counter, sleeper, jitter)
            periods = []
            for calendar in calendars:
                periods.extend(_calendar_events(
                    client,
                    access_token,
                    calendar,
                    range_start,
                    range_end,
                    retry_counter,
                    sleeper,
                    jitter,
                ))
        except CalendarProviderError as exc:
            if exc.code != "authentication_failed":
                raise
            access_token = valid_access_token(integration, force_refresh=True)
            calendars = _selected_calendars(client, access_token, retry_counter, sleeper, jitter)
            periods = []
            for calendar in calendars:
                periods.extend(_calendar_events(
                    client,
                    access_token,
                    calendar,
                    range_start,
                    range_end,
                    retry_counter,
                    sleeper,
                    jitter,
                ))
        periods = merge_busy_periods(periods)
        cache_busy_periods(
            integration,
            periods,
            range_start,
            range_end,
            current_app.config["DEFAULT_TIMEZONE"],
        )
        integration.retry_count = retry_counter[0]
        db.session.commit()
        return CalendarSyncResult(True, "live", periods, integration.last_synced_at)
    except CalendarProviderError as exc:
        db.session.rollback()
        integration = db.session.get(IntegrationState, integration.id)
        integration.retry_count = retry_counter[0]
        integration.last_error_code = exc.code
        if exc.code in {"authentication_failed", "refresh_token_missing", "invalid_grant"}:
            integration.status = "expired"
        has_cache = cache_covers(integration, range_start, range_end)
        if has_cache and exc.temporary and integration.status == "error":
            integration.status = "connected"
        integration.sync_status = "cached" if has_cache else "error"
        db.session.commit()
        cached = _cached_conflicts(integration, range_start.date(), 7) if has_cache else []
        return CalendarSyncResult(False, "cache" if has_cache else "error", cached, integration.last_synced_at, exc.code)
