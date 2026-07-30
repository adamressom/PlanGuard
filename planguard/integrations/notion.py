import base64
import json
from datetime import date, datetime, time, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app

from .. import db
from ..models import Assignment, IntegrationState, NotionImportSource, OAuthCredential
from ..services.calendar import CalendarProviderError, decrypt_token, encrypt_token

NOTION_PROVIDER = "notion"
NOTION_API_ROOT = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"
NOTION_AUTH_ENDPOINT = f"{NOTION_API_ROOT}/oauth/authorize"
NOTION_TOKEN_ENDPOINT = f"{NOTION_API_ROOT}/oauth/token"
NOTION_REVOKE_ENDPOINT = f"{NOTION_API_ROOT}/oauth/revoke"


class NotionProviderError(RuntimeError):
    def __init__(self, code, temporary=False):
        super().__init__(code)
        self.code = code
        self.temporary = temporary


def notion_integration_for_user(user_id, create=False):
    integration = db.session.scalar(
        db.select(IntegrationState).where(
            IntegrationState.user_id == user_id,
            IntegrationState.provider == NOTION_PROVIDER,
        )
    )
    if integration is None and create:
        integration = IntegrationState(
            user_id=user_id,
            provider=NOTION_PROVIDER,
            status="disconnected",
        )
        db.session.add(integration)
        db.session.flush()
    return integration


class NotionClient:
    def _basic_header(self):
        raw = f"{current_app.config['NOTION_CLIENT_ID']}:{current_app.config['NOTION_CLIENT_SECRET']}"
        return "Basic " + base64.b64encode(raw.encode()).decode()

    def build_authorization_url(self, state):
        return f"{NOTION_AUTH_ENDPOINT}?{urlencode({
            'owner': 'user',
            'client_id': current_app.config['NOTION_CLIENT_ID'],
            'redirect_uri': current_app.config['NOTION_OAUTH_REDIRECT_URI'],
            'response_type': 'code',
            'state': state,
        })}"

    def _request(self, method, url, token=None, payload=None, basic=False):
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }
        if basic:
            headers["Authorization"] = self._basic_header()
        elif token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            url,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=10) as response:
                body = response.read().decode()
                result = json.loads(body) if body else {}
        except HTTPError as exc:
            code = "provider_rejected_request"
            try:
                code = json.loads(exc.read().decode()).get("code", code)
            except (ValueError, AttributeError):
                pass
            if exc.code == 401:
                code = "unauthorized"
            elif exc.code == 429:
                code = "rate_limited"
            raise NotionProviderError(code, temporary=exc.code == 429 or exc.code >= 500) from exc
        except (URLError, TimeoutError) as exc:
            raise NotionProviderError("provider_unavailable", temporary=True) from exc
        except (UnicodeDecodeError, ValueError) as exc:
            raise NotionProviderError("invalid_provider_response") from exc
        if not isinstance(result, dict):
            raise NotionProviderError("invalid_provider_response")
        return result

    def exchange_code(self, code):
        return self._request("POST", NOTION_TOKEN_ENDPOINT, payload={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": current_app.config["NOTION_OAUTH_REDIRECT_URI"],
        }, basic=True)

    def refresh_access_token(self, refresh_token):
        return self._request("POST", NOTION_TOKEN_ENDPOINT, payload={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }, basic=True)

    def revoke_token(self, token):
        return self._request("POST", NOTION_REVOKE_ENDPOINT, payload={"token": token}, basic=True)

    def search_source_page(self, token, cursor=None):
        payload = {"filter": {"property": "object", "value": "data_source"}, "page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        return self._request("POST", f"{NOTION_API_ROOT}/search", token, payload)

    def retrieve_source(self, token, source_id):
        return self._request("GET", f"{NOTION_API_ROOT}/data_sources/{source_id}", token)

    def query_source_page(self, token, source_id, cursor=None):
        payload = {"page_size": 100, "result_type": "page"}
        if cursor:
            payload["start_cursor"] = cursor
        return self._request("POST", f"{NOTION_API_ROOT}/data_sources/{source_id}/query", token, payload)


class DemoNotionClient:
    source_id = "demo-coursework-source"

    def search_source_page(self, token, cursor=None):
        return {
            "results": [{"id": self.source_id, "object": "data_source", "title": _rich_text("Coursework")}],
            "has_more": False,
            "next_cursor": None,
        }

    def retrieve_source(self, token, source_id):
        if source_id != self.source_id:
            raise NotionProviderError("object_not_found")
        return {
            "id": self.source_id,
            "title": _rich_text("Coursework"),
            "properties": {
                "Assignment": {"id": "title", "name": "Assignment", "type": "title"},
                "Due": {"id": "due", "name": "Due", "type": "date"},
                "Course": {"id": "course", "name": "Course", "type": "select"},
                "Estimate": {"id": "estimate", "name": "Estimate", "type": "number"},
                "Difficulty": {"id": "difficulty", "name": "Difficulty", "type": "number"},
                "Done": {"id": "done", "name": "Done", "type": "checkbox"},
                "Notes": {"id": "notes", "name": "Notes", "type": "rich_text"},
            },
        }

    def query_source_page(self, token, source_id, cursor=None):
        today = datetime.now(timezone.utc).date()
        rows = [
            _demo_page("demo-notion-1", "Calculus problem set", today + timedelta(days=2), "MATH 201", 75, 4, False),
            _demo_page("demo-notion-2", "History reading response", today + timedelta(days=4), "HIST 110", 45, 2, False),
            _demo_page("demo-notion-3", "Chemistry lab write-up", today + timedelta(days=6), "CHEM 220", 120, 5, False),
        ]
        return {"results": rows, "has_more": False, "next_cursor": None}


def notion_client():
    configured = current_app.config.get("NOTION_CLIENT")
    if configured:
        return configured() if isinstance(configured, type) else configured
    if current_app.config["NOTION_MODE"] == "demo":
        return DemoNotionClient()
    return NotionClient()


def _rich_text(value):
    return [{"type": "text", "plain_text": value, "text": {"content": value}}]


def _demo_page(page_id, title, deadline, course, estimate, difficulty, done):
    return {
        "id": page_id,
        "object": "page",
        "properties": {
            "Assignment": {"type": "title", "title": _rich_text(title)},
            "Due": {"type": "date", "date": {"start": deadline.isoformat(), "end": None}},
            "Course": {"type": "select", "select": {"name": course}},
            "Estimate": {"type": "number", "number": estimate},
            "Difficulty": {"type": "number", "number": difficulty},
            "Done": {"type": "checkbox", "checkbox": done},
            "Notes": {"type": "rich_text", "rich_text": _rich_text("Imported from the demo Notion source.")},
        },
    }


def _title(value):
    if not isinstance(value, list):
        return ""
    return "".join(str(item.get("plain_text", "")) for item in value if isinstance(item, dict)).strip()


def source_name(source):
    return _title(source.get("title", [])) or source.get("name") or "Notion source"


def store_notion_tokens(integration, payload):
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not access_token or not refresh_token:
        raise NotionProviderError("invalid_token_response")
    credential = integration.credential or OAuthCredential(integration=integration)
    if credential.id is None:
        db.session.add(credential)
    try:
        credential.encrypted_access_token = encrypt_token(access_token)
        credential.encrypted_refresh_token = encrypt_token(refresh_token)
    except CalendarProviderError as exc:
        raise NotionProviderError(exc.code) from exc
    expires_in = payload.get("expires_in")
    credential.access_token_expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        if isinstance(expires_in, (int, float)) and expires_in > 0
        else None
    )
    credential.token_type = payload.get("token_type", "Bearer")
    credential.encryption_key_version = current_app.config["TOKEN_ENCRYPTION_KEY_VERSION"]
    integration.provider_account_id = payload.get("bot_id") or integration.provider_account_id
    integration.provider_account_email = None
    current_workspace = integration.cached_payload or {}
    integration.cached_payload = {
        "workspace_id": payload.get("workspace_id") or current_workspace.get("workspace_id"),
        "workspace_name": payload.get("workspace_name") or current_workspace.get("workspace_name") or "Notion workspace",
    }


def notion_access_token(integration):
    if integration.mode == "demo":
        return "demo-token"
    credential = integration.credential
    if credential is None or not credential.encrypted_access_token:
        raise NotionProviderError("connection_expired")
    expiry = credential.access_token_expires_at
    if expiry is None or (expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry) > datetime.now(timezone.utc) + timedelta(minutes=5):
        try:
            return decrypt_token(credential.encrypted_access_token)
        except CalendarProviderError as exc:
            raise NotionProviderError(exc.code) from exc
    if not credential.encrypted_refresh_token:
        raise NotionProviderError("connection_expired")
    try:
        refresh_token = decrypt_token(credential.encrypted_refresh_token)
    except CalendarProviderError as exc:
        raise NotionProviderError(exc.code) from exc
    payload = notion_client().refresh_access_token(refresh_token)
    store_notion_tokens(integration, payload)
    db.session.commit()
    try:
        return decrypt_token(credential.encrypted_access_token)
    except CalendarProviderError as exc:
        raise NotionProviderError(exc.code) from exc


def list_sources(integration):
    client = notion_client()
    token = notion_access_token(integration)
    sources = []
    cursor = None
    while True:
        payload = client.search_source_page(token, cursor)
        results = payload.get("results")
        if not isinstance(results, list):
            raise NotionProviderError("invalid_provider_response")
        sources.extend({
            "id": item["id"],
            "name": source_name(item),
        } for item in results if isinstance(item, dict) and item.get("id"))
        if not payload.get("has_more"):
            return sources
        cursor = payload.get("next_cursor")
        if not cursor:
            raise NotionProviderError("invalid_provider_response")


def schema_for_source(integration, source_id):
    source = notion_client().retrieve_source(notion_access_token(integration), source_id)
    properties = source.get("properties")
    if not isinstance(properties, dict):
        raise NotionProviderError("invalid_provider_response")
    schema = {
        name: {"id": item.get("id"), "type": item.get("type")}
        for name, item in properties.items()
        if isinstance(item, dict) and item.get("type")
    }
    return source_name(source), schema


MAPPING_TYPES = {
    "title": {"title", "rich_text"},
    "deadline": {"date"},
    "course": {"select", "status", "rich_text", "title"},
    "difficulty": {"number", "select"},
    "estimated_minutes": {"number"},
    "course_weight": {"number"},
    "progress": {"number", "formula"},
    "completed": {"checkbox", "status", "select"},
    "notes": {"rich_text", "title"},
}
REQUIRED_MAPPINGS = {"title", "deadline"}


def default_mapping(schema):
    hints = {
        "title": ("assignment", "task", "name", "title"),
        "deadline": ("due", "deadline", "date"),
        "course": ("course", "class", "subject"),
        "difficulty": ("difficulty",),
        "estimated_minutes": ("estimate", "minutes", "effort"),
        "course_weight": ("weight", "impact"),
        "progress": ("progress",),
        "completed": ("done", "complete", "completed", "status"),
        "notes": ("notes", "description"),
    }
    mapping = {}
    for field, names in hints.items():
        compatible = MAPPING_TYPES[field]
        candidates = [
            name for name, item in schema.items()
            if item["type"] in compatible
        ]
        match = next((name for name in candidates if name.lower() in names), None)
        if match is None and field in REQUIRED_MAPPINGS and candidates:
            match = candidates[0]
        mapping[field] = match or ""
    return mapping


def validate_mapping(schema, mapping):
    errors = {}
    cleaned = {}
    for field, compatible in MAPPING_TYPES.items():
        property_name = str(mapping.get(field, "")).strip()
        cleaned[field] = property_name
        if field in REQUIRED_MAPPINGS and not property_name:
            errors[field] = f"{field.replace('_', ' ').title()} mapping is required."
        elif property_name and (
            property_name not in schema or schema[property_name]["type"] not in compatible
        ):
            errors[field] = "Choose a compatible Notion property."
    return cleaned, errors


def query_source_rows(integration, source):
    client = notion_client()
    token = notion_access_token(integration)
    rows = []
    cursor = None
    while True:
        payload = client.query_source_page(token, source.data_source_id, cursor)
        results = payload.get("results")
        if not isinstance(results, list):
            raise NotionProviderError("invalid_provider_response")
        rows.extend(item for item in results if isinstance(item, dict) and item.get("object") == "page")
        if not payload.get("has_more"):
            return rows
        cursor = payload.get("next_cursor")
        if not cursor:
            raise NotionProviderError("invalid_provider_response")


def _property_value(property_value):
    if not isinstance(property_value, dict):
        return None
    property_type = property_value.get("type")
    value = property_value.get(property_type)
    if property_type in {"title", "rich_text"}:
        return _title(value)
    if property_type in {"select", "status"}:
        return value.get("name") if isinstance(value, dict) else None
    if property_type == "date":
        return value.get("start") if isinstance(value, dict) else None
    if property_type in {"number", "checkbox"}:
        return value
    if property_type == "formula" and isinstance(value, dict):
        formula_type = value.get("type")
        return value.get(formula_type)
    return None


def _mapped(properties, mapping, field):
    property_name = mapping.get(field)
    return _property_value(properties.get(property_name)) if property_name else None


def _number(value, default, minimum, maximum):
    if isinstance(value, bool):
        return default, True
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default, value not in (None, "")
    if not minimum <= number <= maximum:
        return default, True
    return number, False


def _deadline(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(str(value)), time(23, 59), tzinfo=timezone.utc)
        except ValueError:
            return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def convert_page(page, source):
    properties = page.get("properties") or {}
    mapping = source.property_mapping or {}
    title = str(_mapped(properties, mapping, "title") or "").strip()
    deadline = _deadline(_mapped(properties, mapping, "deadline"))
    errors = []
    warnings = []
    if not title:
        errors.append("Missing title")
    if deadline is None:
        errors.append("Missing or invalid deadline")
    difficulty, warning = _number(_mapped(properties, mapping, "difficulty"), 3, 1, 5)
    if warning:
        warnings.append("Difficulty defaulted to 3")
    estimate, warning = _number(_mapped(properties, mapping, "estimated_minutes"), 60, 1, 1440)
    if warning:
        warnings.append("Estimated minutes defaulted to 60")
    weight, warning = _number(_mapped(properties, mapping, "course_weight"), 10, 0, 100)
    if warning:
        warnings.append("Course impact defaulted to 10")
    progress, warning = _number(_mapped(properties, mapping, "progress"), 0, 0, 100)
    if warning:
        warnings.append("Progress defaulted to 0")
    completed_value = _mapped(properties, mapping, "completed")
    completed = (
        completed_value is True
        or str(completed_value or "").strip().lower() in {"done", "complete", "completed"}
    )
    if completed:
        progress = 100
    return {
        "provider_id": page.get("id"),
        "title": title[:180],
        "course": str(_mapped(properties, mapping, "course") or source.source_name)[:120],
        "deadline": deadline,
        "difficulty": int(difficulty),
        "estimated_minutes": int(estimate),
        "course_weight": float(weight),
        "progress": int(progress),
        "completed": completed,
        "notes": str(_mapped(properties, mapping, "notes") or ""),
        "errors": errors,
        "warnings": warnings,
    }


def prepare_import(user_id, source):
    rows = query_source_rows(source.integration, source)
    provider_ids = [row.get("id") for row in rows if row.get("id")]
    existing_ids = set(db.session.scalars(
        db.select(Assignment.provider_id).where(
            Assignment.user_id == user_id,
            Assignment.provider == NOTION_PROVIDER,
            Assignment.provider_id.in_(provider_ids),
        )
    ).all()) if provider_ids else set()
    ready = []
    skipped = []
    duplicates = []
    for row in rows:
        converted = convert_page(row, source)
        if converted["provider_id"] in existing_ids:
            duplicates.append(converted)
        elif converted["errors"]:
            skipped.append(converted)
        else:
            ready.append(converted)
    return {"ready": ready, "duplicates": duplicates, "skipped": skipped, "total": len(rows)}


def import_prepared(user_id, source, prepared):
    for item in prepared["ready"]:
        db.session.add(Assignment(
            user_id=user_id,
            provider=NOTION_PROVIDER,
            provider_id=item["provider_id"],
            title=item["title"],
            course=item["course"],
            deadline=item["deadline"],
            difficulty=item["difficulty"],
            estimated_minutes=item["estimated_minutes"],
            course_weight=item["course_weight"],
            progress=item["progress"],
            completed=item["completed"],
            notes=item["notes"],
        ))
    summary = {
        "imported": len(prepared["ready"]),
        "already_imported": len(prepared["duplicates"]),
        "skipped": len(prepared["skipped"]),
        "total": prepared["total"],
    }
    completed_at = datetime.now(timezone.utc)
    source.last_imported_at = completed_at
    source.last_summary = summary
    source.integration.sync_status = "live"
    source.integration.last_synced_at = completed_at
    source.integration.last_error_code = None
    db.session.commit()
    return summary
