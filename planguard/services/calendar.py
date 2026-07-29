import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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


class CalendarProviderError(RuntimeError):
    def __init__(self, code, temporary=False):
        super().__init__(code)
        self.code = code
        self.temporary = temporary


@dataclass(frozen=True)
class CalendarStatus:
    mode: str
    status: str
    connected: bool
    last_synced_at: datetime | None
    last_error_code: str | None
    busy_count: int = 0


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
    return CalendarStatus(
        mode=integration.mode if integration and integration.mode else mode,
        status=integration.status if integration else "disconnected",
        connected=connected,
        last_synced_at=integration.last_synced_at if integration else None,
        last_error_code=integration.last_error_code if integration else None,
        busy_count=busy_count,
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
    range_start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    range_end = range_start + timedelta(days=days)
    conflicts = []
    payload = integration.cached_payload or {}
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


def cache_busy_periods(integration, conflicts):
    integration.cached_payload = {
        "busy_periods": [
            {
                "title": "Busy",
                "starts_at": aware_datetime(item.starts_at).isoformat(),
                "ends_at": aware_datetime(item.ends_at).isoformat(),
            }
            for item in merge_busy_periods(conflicts)
        ]
    }
    integration.last_synced_at = datetime.now(timezone.utc)
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
