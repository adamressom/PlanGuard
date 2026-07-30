import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request, session, url_for

from . import db
from .integrations.notion import (
    NOTION_PROVIDER,
    NotionProviderError,
    notion_access_token,
    notion_client,
    notion_integration_for_user,
)
from .models import Assignment, FocusSession, IntegrationState
from .services.assignments import create_assignment, remove_assignment, update_assignment
from .services.calendar import (
    CalendarProviderError,
    GOOGLE_PROVIDER,
    decrypt_token,
    google_integration_for_user,
    oauth_client,
    sync_google_calendar,
)
from .services.focus import (
    FocusStateError,
    active_focus_for_user,
    end_focus_session,
    focus_payload,
    pause_focus_session,
    recent_focus_history,
    resume_focus_session,
    start_focus_session,
)
from .services.ownership import get_owned_record, owned_records
from .services.priority import assignment_priority_input, explain_priority

api = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def success(data=None, status=200, meta=None):
    payload = {"data": data}
    if meta is not None:
        payload["meta"] = meta
    return jsonify(payload), status


def error(code, message, status=400, fields=None):
    detail = {"code": code, "message": message}
    if fields:
        detail["fields"] = fields
    return jsonify(error=detail), status


def v1_login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return error("authentication_required", "Authentication is required.", 401)
        return view(**kwargs)
    return wrapped


def assignment_json(assignment):
    return {
        "id": assignment.id,
        "title": assignment.title,
        "course": assignment.course,
        "deadline": assignment.deadline.isoformat(),
        "difficulty": assignment.difficulty,
        "estimated_minutes": assignment.estimated_minutes,
        "course_impact": assignment.course_weight,
        "progress": assignment.progress,
        "completed": assignment.completed,
        "notes": assignment.notes,
        "provider": assignment.provider,
        "provider_id": assignment.provider_id,
    }


def integration_json(integration, provider=None):
    provider = provider or integration.provider
    if integration is None:
        return {
            "provider": provider,
            "status": "disconnected",
            "sync_status": "never",
            "display_status": "Disconnected",
            "next_action": "Connect",
            "last_successful_sync_at": None,
        }
    last_successful = integration.last_synced_at
    if provider == NOTION_PROVIDER and integration.notion_source:
        last_successful = integration.notion_source.last_imported_at or last_successful
    if integration.status == "disconnected":
        display, action = "Disconnected", "Connect"
    elif integration.status == "connecting":
        display, action = "Connecting", "Complete connection"
    elif integration.status == "expired":
        display, action = "Reconnect required", "Reconnect"
    elif integration.sync_status == "syncing":
        display, action = "Syncing", "Wait"
    elif integration.sync_status == "live":
        display, action = "Synced", "Sync again"
    elif integration.sync_status == "cached":
        display, action = "Using cached data", "Retry sync"
    elif integration.sync_status == "error" or integration.status == "error":
        display, action = "Error", "Retry or reconnect"
    else:
        display, action = "Connected", "Choose source" if provider == NOTION_PROVIDER else "Sync calendar"
    return {
        "id": integration.id,
        "provider": provider,
        "mode": integration.mode,
        "status": integration.status,
        "sync_status": integration.sync_status,
        "display_status": display,
        "next_action": action,
        "last_successful_sync_at": last_successful.isoformat() if last_successful else None,
        "last_sync_attempt_at": integration.last_sync_attempt_at.isoformat() if integration.last_sync_attempt_at else None,
        "retry_count": integration.retry_count,
    }


def json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, error("invalid_json", "A JSON object request body is required.", 400)
    return body, None


@api.get("/assignments")
@v1_login_required
def assignments_collection():
    records = db.session.scalars(
        owned_records(Assignment).order_by(Assignment.deadline, Assignment.id)
    ).all()
    return success([assignment_json(item) for item in records], meta={"count": len(records)})


@api.post("/assignments")
@v1_login_required
def create_assignment_api():
    body, failure = json_body()
    if failure:
        return failure
    assignment, errors = create_assignment(g.user.id, body)
    if errors:
        return error("validation_error", "Assignment validation failed.", 422, errors)
    return success(assignment_json(assignment), 201)


@api.get("/assignments/<int:assignment_id>")
@v1_login_required
def assignment_detail_api(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        return error("not_found", "Assignment not found.", 404)
    return success(assignment_json(assignment))


@api.patch("/assignments/<int:assignment_id>")
@v1_login_required
def assignment_update_api(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        return error("not_found", "Assignment not found.", 404)
    body, failure = json_body()
    if failure:
        return failure
    merged = {
        "title": assignment.title,
        "course": assignment.course,
        "deadline": assignment.deadline.isoformat(),
        "difficulty": assignment.difficulty,
        "estimated_minutes": assignment.estimated_minutes,
        "course_impact": assignment.course_weight,
        "progress": assignment.progress,
        "completed": assignment.completed,
        "notes": assignment.notes,
        "provider_id": assignment.provider_id or "",
    }
    merged.update(body)
    updated, errors = update_assignment(assignment, merged)
    if errors:
        return error("validation_error", "Assignment validation failed.", 422, errors)
    return success(assignment_json(updated))


@api.delete("/assignments/<int:assignment_id>")
@v1_login_required
def assignment_delete_api(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        return error("not_found", "Assignment not found.", 404)
    removed_id = assignment.id
    remove_assignment(assignment)
    return success({"id": removed_id, "deleted": True})


@api.get("/assignments/<int:assignment_id>/priority-explanation")
@v1_login_required
def priority_explanation_api(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        return error("not_found", "Assignment not found.", 404)
    explanation = explain_priority(
        assignment_priority_input(assignment),
        available_minutes=g.user.available_study_minutes,
    )
    return success(explanation)


@api.get("/focus-sessions/active")
@v1_login_required
def focus_active_api():
    focus = active_focus_for_user(g.user.id)
    return success(focus_payload(focus) if focus else None)


@api.get("/focus-sessions")
@v1_login_required
def focus_history_api():
    records = recent_focus_history(g.user.id)
    return success([focus_payload(item) for item in records], meta={"count": len(records)})


@api.post("/focus-sessions")
@v1_login_required
def focus_start_api():
    body, failure = json_body()
    if failure:
        return failure
    assignment_id = body.get("assignment_id")
    planned_minutes = body.get("planned_minutes")
    if isinstance(assignment_id, bool) or not isinstance(assignment_id, int):
        return error("validation_error", "Focus-session validation failed.", 422, {
            "assignment_id": "A valid assignment ID is required."
        })
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        return error("not_found", "Assignment not found.", 404)
    try:
        focus = start_focus_session(g.user.id, assignment, planned_minutes)
    except FocusStateError as exc:
        if active_focus_for_user(g.user.id) is None:
            return error("validation_error", "Focus-session validation failed.", 422, {
                "planned_minutes": str(exc)
            })
        return error("focus_state_conflict", str(exc), 409)
    return success(focus_payload(focus), 201)


def _owned_focus(focus_session_id):
    focus = get_owned_record(FocusSession, focus_session_id)
    if focus is None:
        return None, error("not_found", "Focus session not found.", 404)
    return focus, None


@api.post("/focus-sessions/<int:focus_session_id>/pause")
@v1_login_required
def focus_pause_api(focus_session_id):
    focus, failure = _owned_focus(focus_session_id)
    if failure:
        return failure
    try:
        pause_focus_session(focus)
    except FocusStateError as exc:
        return error("focus_state_conflict", str(exc), 409)
    return success(focus_payload(focus))


@api.post("/focus-sessions/<int:focus_session_id>/resume")
@v1_login_required
def focus_resume_api(focus_session_id):
    focus, failure = _owned_focus(focus_session_id)
    if failure:
        return failure
    try:
        resume_focus_session(focus)
    except FocusStateError as exc:
        return error("focus_state_conflict", str(exc), 409)
    return success(focus_payload(focus))


@api.post("/focus-sessions/<int:focus_session_id>/end")
@v1_login_required
def focus_end_api(focus_session_id):
    focus, failure = _owned_focus(focus_session_id)
    if failure:
        return failure
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return error("invalid_json", "A JSON object request body is required.", 400)
    try:
        end_focus_session(focus, timer_complete=body.get("reason") == "timer_complete")
    except FocusStateError as exc:
        return error("focus_state_conflict", str(exc), 409)
    return success(focus_payload(focus))


def _start_attempt(provider):
    state = secrets.token_urlsafe(32)
    session_key = "google_oauth_attempt" if provider == GOOGLE_PROVIDER else "notion_oauth_attempt"
    session[session_key] = {
        "state": state,
        "user_id": g.user.id,
        "provider": provider,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return state


@api.get("/integrations/<provider>/status")
@v1_login_required
def integration_status_api(provider):
    if provider == GOOGLE_PROVIDER:
        integration = google_integration_for_user(g.user.id)
    elif provider == NOTION_PROVIDER:
        integration = notion_integration_for_user(g.user.id)
    else:
        return error("not_found", "Integration provider not found.", 404)
    return success(integration_json(integration, provider))


@api.post("/integrations/<provider>/connect")
@v1_login_required
def integration_connect_api(provider):
    if provider == GOOGLE_PROVIDER:
        mode = current_app.config["GOOGLE_CALENDAR_MODE"]
        configured = current_app.config["GOOGLE_OAUTH_CONFIGURED"]
        integration = google_integration_for_user(g.user.id, create=True)
    elif provider == NOTION_PROVIDER:
        mode = current_app.config["NOTION_MODE"]
        configured = current_app.config["NOTION_OAUTH_CONFIGURED"]
        integration = notion_integration_for_user(g.user.id, create=True)
    else:
        return error("not_found", "Integration provider not found.", 404)
    if mode == "disabled":
        return error("integration_disabled", "This integration is unavailable.", 409)
    if mode == "live" and not configured:
        return error("integration_not_configured", "Live integration credentials are not configured.", 503)
    if integration.status == "connected":
        return error("already_connected", "Disconnect before replacing this integration.", 409)
    state = _start_attempt(provider)
    integration.mode = mode
    integration.status = "connecting"
    integration.last_error_code = None
    db.session.commit()
    if provider == GOOGLE_PROVIDER:
        connect_url = (
            url_for("main.google_calendar_demo_consent", _external=False)
            if mode == "demo"
            else oauth_client().build_authorization_url(state, force_consent=integration.credential is None)
        )
    else:
        connect_url = (
            url_for("main.notion_demo_consent", _external=False)
            if mode == "demo"
            else notion_client().build_authorization_url(state)
        )
    return success({"provider": provider, "status": "connecting", "authorization_url": connect_url}, 202)


@api.post("/integrations/<provider>/sync")
@v1_login_required
def integration_sync_api(provider):
    if provider != GOOGLE_PROVIDER:
        return error("operation_not_supported", "This provider does not support a sync endpoint.", 405)
    integration = google_integration_for_user(g.user.id)
    if integration is None or integration.status != "connected":
        return error("not_connected", "Connect Google Calendar before syncing.", 409)
    result = sync_google_calendar(integration)
    payload = {
        "integration": integration_json(integration),
        "source": result.source,
        "busy_period_count": len(result.busy_periods),
    }
    if result.ok:
        return success(payload)
    if result.source == "cache":
        return success(payload, meta={"warning": "Live sync failed; cached calendar data is in use."})
    return error("sync_failed", "Calendar sync failed. Retry or reconnect.", 502)


@api.post("/integrations/<provider>/disconnect")
@v1_login_required
def integration_disconnect_api(provider):
    if provider == GOOGLE_PROVIDER:
        integration = google_integration_for_user(g.user.id)
    elif provider == NOTION_PROVIDER:
        integration = notion_integration_for_user(g.user.id)
    else:
        return error("not_found", "Integration provider not found.", 404)
    if integration is None:
        return success({"provider": provider, "status": "disconnected"})
    session.pop("google_oauth_attempt" if provider == GOOGLE_PROVIDER else "notion_oauth_attempt", None)
    if integration.credential:
        try:
            if provider == GOOGLE_PROVIDER:
                encrypted = integration.credential.encrypted_refresh_token or integration.credential.encrypted_access_token
                if encrypted:
                    oauth_client().revoke_token(decrypt_token(encrypted))
            else:
                notion_client().revoke_token(notion_access_token(integration))
        except (CalendarProviderError, NotionProviderError):
            pass
        db.session.delete(integration.credential)
    if provider == NOTION_PROVIDER and integration.notion_source:
        db.session.delete(integration.notion_source)
    integration.mode = None
    integration.status = "disconnected"
    integration.sync_status = "never"
    integration.cached_payload = None
    integration.last_synced_at = None
    integration.last_sync_attempt_at = None
    integration.last_error_code = None
    integration.provider_account_id = None
    db.session.commit()
    return success({"provider": provider, "status": "disconnected"})


@api.errorhandler(404)
def blueprint_not_found(_exc):
    return error("not_found", "API endpoint not found.", 404)


@api.errorhandler(405)
def blueprint_method_not_allowed(_exc):
    return error("method_not_allowed", "HTTP method not allowed for this endpoint.", 405)
