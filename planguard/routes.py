import hmac
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for

from . import db
from .auth import api_login_required, login_required
from .models import Assignment, AvailabilityOverride, FocusSession, IntegrationState, ScheduledFocusBlock, WeeklyAvailability
from .services.calendar import (
    CalendarProviderError,
    GOOGLE_PROVIDER,
    GOOGLE_SCOPES,
    cache_busy_periods,
    calendar_conflicts_for_user,
    calendar_status_for_user,
    demo_busy_periods,
    google_integration_for_user,
    oauth_client,
    store_token_response,
)
from .services.assignments import create_assignment, remove_assignment, set_assignment_status, update_assignment as save_assignment_updates
from .services.focus import FocusStateError, active_focus_for_user, end_focus_session, focus_payload, pause_focus_session, recent_focus_history, resume_focus_session, start_focus_session
from .services.ownership import get_owned_record, owned_records
from .services.priority import assignment_priority_input, rank_assignments
from .services.scheduling import parse_date, parse_time, recommendation_for_assignment, validate_scheduled_block

main = Blueprint("main", __name__)


def assignment_payload(assignment):
    return {
        "id": assignment.id,
        "title": assignment.title,
        "course": assignment.course,
        "deadline": assignment.deadline.isoformat(),
        "difficulty": assignment.difficulty,
        "estimated_minutes": assignment.estimated_minutes,
        "course_impact": assignment.course_impact,
        "progress": assignment.progress,
        "completed": assignment.completed,
        "notes": assignment.notes,
        "provider_id": assignment.provider_id,
    }


def integration_payload(integration):
    return {
        "id": integration.id,
        "provider": integration.provider,
        "mode": integration.mode,
        "status": integration.status,
        "last_synced_at": integration.last_synced_at.isoformat() if integration.last_synced_at else None,
        "retry_count": integration.retry_count,
    }


def calendar_recommendation(assignment, start_day=None, days=7):
    conflicts = calendar_conflicts_for_user(g.user.id, start_day, days)
    return recommendation_for_assignment(
        assignment,
        g.user,
        start_day=start_day,
        days=days,
        calendar_conflicts=conflicts,
    )


def api_not_found():
    return jsonify(error="Record not found."), 404


def ranked_active_assignments_payload():
    active_records = db.session.scalars(
        owned_records(Assignment).where(Assignment.completed.is_(False))
    ).all()
    ranked = rank_assignments(
        [assignment_priority_input(item) for item in active_records],
        available_minutes=g.user.available_study_minutes,
    )
    return [
        {
            **assignment,
            "detail_url": url_for("main.assignment_detail", assignment_id=assignment["id"]),
            "edit_url": url_for("main.edit_assignment", assignment_id=assignment["id"]),
            "delete_url": url_for("main.delete_assignment_page", assignment_id=assignment["id"]),
        }
        for assignment in ranked
    ]


@main.get("/")
def landing():
    return render_template("landing.html")


@main.get("/dashboard")
@login_required
def dashboard():
    active_records = db.session.scalars(
        owned_records(Assignment).where(Assignment.completed.is_(False))
    ).all()
    completed_assignments = db.session.scalars(
        owned_records(Assignment)
        .where(Assignment.completed.is_(True))
        .order_by(Assignment.deadline.desc())
    ).all()
    active_assignments = rank_assignments(
        [assignment_priority_input(item) for item in active_records],
        available_minutes=g.user.available_study_minutes,
    )
    active_focus = active_focus_for_user(g.user.id)
    active_focus_progress = None
    if active_focus and active_focus.assignment_id:
        active_focus_assignment = get_owned_record(Assignment, active_focus.assignment_id)
        active_focus_progress = active_focus_assignment.progress if active_focus_assignment else 0
    focus_history = recent_focus_history(g.user.id)
    upcoming_blocks = db.session.scalars(
        owned_records(ScheduledFocusBlock)
        .where(ScheduledFocusBlock.status == "scheduled")
        .order_by(ScheduledFocusBlock.starts_at)
        .limit(3)
    ).all()
    recommended = active_assignments[0] if active_assignments else None
    recommended_focus_minutes = 0
    if recommended and g.user.available_study_minutes > 0:
        recommended_focus_minutes = max(1, min(
            int(recommended["estimated_minutes"] or 1),
            g.user.available_study_minutes,
            50,
        ))
    return render_template(
        "dashboard.html",
        assignments=active_assignments,
        completed_assignments=completed_assignments,
        recommended=recommended,
        available_minutes=g.user.available_study_minutes,
        active_focus=focus_payload(active_focus) if active_focus else None,
        active_focus_progress=active_focus_progress,
        recommended_focus_minutes=recommended_focus_minutes,
        focus_history=[focus_payload(item) for item in focus_history],
        upcoming_blocks=upcoming_blocks,
        calendar_status=calendar_status_for_user(g.user.id),
    )


@main.post("/preferences/availability")
@login_required
def update_availability():
    raw_minutes = request.form.get("available_minutes", "").strip()
    try:
        minutes = int(raw_minutes)
    except (TypeError, ValueError):
        minutes = None

    if minutes is None or not 0 <= minutes <= 1440:
        flash("Available study time must be a whole number from 0 to 1440 minutes.", "error")
    else:
        g.user.available_study_minutes = minutes
        db.session.commit()
        flash(f"Your daily study window is now {minutes} minutes.", "success")
    return redirect(url_for("main.dashboard"))


@main.get("/availability")
@login_required
def availability_page():
    weekly_windows = db.session.scalars(
        owned_records(WeeklyAvailability).order_by(WeeklyAvailability.weekday, WeeklyAvailability.starts_at_time)
    ).all()
    overrides = db.session.scalars(
        owned_records(AvailabilityOverride).order_by(AvailabilityOverride.date, AvailabilityOverride.starts_at_time)
    ).all()
    calendar_status = calendar_status_for_user(g.user.id)
    calendar_conflicts = calendar_conflicts_for_user(g.user.id)
    return render_template("availability_page.html", weekly_windows=weekly_windows, overrides=overrides, calendar_status=calendar_status, calendar_conflicts=calendar_conflicts, weekdays=[
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ])


def _begin_google_oauth_attempt():
    state = secrets.token_urlsafe(32)
    session["google_oauth_attempt"] = {
        "state": state,
        "user_id": g.user.id,
        "provider": GOOGLE_PROVIDER,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return state


def _consume_google_oauth_attempt(returned_state):
    attempt = session.pop("google_oauth_attempt", None)
    if not attempt or not returned_state:
        return False
    try:
        created_at = datetime.fromisoformat(attempt["created_at"])
        valid = (
            attempt["user_id"] == g.user.id
            and attempt["provider"] == GOOGLE_PROVIDER
            and datetime.now(timezone.utc) - created_at <= timedelta(minutes=10)
            and hmac.compare_digest(attempt["state"], returned_state)
        )
    except (KeyError, TypeError, ValueError):
        return False
    return valid


@main.post("/integrations/google-calendar/connect")
@login_required
def connect_google_calendar():
    mode = current_app.config["GOOGLE_CALENDAR_MODE"]
    if mode == "disabled":
        flash("Google Calendar integration is unavailable.", "error")
        return redirect(url_for("main.dashboard"))
    if mode == "live" and not current_app.config["GOOGLE_OAUTH_CONFIGURED"]:
        flash("Google Calendar live connection is not configured.", "error")
        return redirect(url_for("main.dashboard"))
    integration = google_integration_for_user(g.user.id, create=True)
    if integration.status == "connected" and request.form.get("reconnect") != "1":
        flash("Disconnect or choose reconnect before replacing this calendar connection.", "error")
        return redirect(url_for("main.dashboard"))
    state = _begin_google_oauth_attempt()
    integration.status = "connecting"
    integration.mode = mode
    integration.last_error_code = None
    db.session.commit()
    if mode == "demo":
        return redirect(url_for("main.google_calendar_demo_consent"))
    return redirect(oauth_client().build_authorization_url(
        state,
        force_consent=request.form.get("reconnect") == "1" or integration.credential is None,
    ))


@main.get("/integrations/google-calendar/demo-consent")
@login_required
def google_calendar_demo_consent():
    attempt = session.get("google_oauth_attempt")
    if not attempt or attempt.get("user_id") != g.user.id:
        flash("That demo connection attempt expired. Please try again.", "error")
        return redirect(url_for("main.dashboard"))
    return render_template("google_calendar_demo_consent.html", state=attempt["state"])


@main.post("/integrations/google-calendar/demo-callback")
@login_required
def google_calendar_demo_callback():
    integration = google_integration_for_user(g.user.id, create=True)
    if not _consume_google_oauth_attempt(request.form.get("state")):
        integration.status = "disconnected"
        integration.last_error_code = "oauth_state_invalid"
        db.session.commit()
        return render_template("google_calendar_oauth_error.html"), 400
    if request.form.get("decision") != "approve":
        integration.status = "disconnected"
        integration.mode = None
        db.session.commit()
        flash("Demo calendar was not connected.", "success")
        return redirect(url_for("main.dashboard"))
    integration.mode = "demo"
    integration.status = "connected"
    integration.connected_at = datetime.now(timezone.utc)
    cache_busy_periods(integration, demo_busy_periods(datetime.now(timezone.utc).date(), 14))
    db.session.commit()
    flash("Demo calendar connected. No Google account data was accessed.", "success")
    return redirect(url_for("main.dashboard"))


@main.get("/integrations/google-calendar/callback")
@login_required
def google_calendar_callback():
    integration = google_integration_for_user(g.user.id, create=True)
    if not _consume_google_oauth_attempt(request.args.get("state")):
        if integration.status != "connected":
            integration.status = "disconnected"
        integration.last_error_code = "oauth_state_invalid"
        db.session.commit()
        return render_template("google_calendar_oauth_error.html"), 400
    if request.args.get("error"):
        integration.status = "disconnected"
        integration.last_error_code = "access_denied" if request.args["error"] == "access_denied" else "provider_error"
        db.session.commit()
        flash("Google Calendar was not connected.", "success" if request.args["error"] == "access_denied" else "error")
        return redirect(url_for("main.dashboard"))
    code = request.args.get("code")
    if not code:
        integration.status = "error"
        integration.last_error_code = "authorization_code_missing"
        db.session.commit()
        return render_template("google_calendar_oauth_error.html"), 400
    try:
        payload = oauth_client().exchange_code(code)
        store_token_response(integration, payload)
        integration.mode = "live"
        integration.status = "connected"
        integration.connected_at = datetime.now(timezone.utc)
        integration.last_error_code = None
        db.session.commit()
    except CalendarProviderError as exc:
        db.session.rollback()
        integration = google_integration_for_user(g.user.id, create=True)
        integration.status = "error"
        integration.last_error_code = exc.code
        db.session.commit()
        flash("Google couldn’t complete the connection. Please try again.", "error")
        return redirect(url_for("main.dashboard"))
    flash("Google Calendar connected.", "success")
    return redirect(url_for("main.dashboard"))


@main.post("/integrations/google-calendar/sync")
@login_required
def sync_google_calendar():
    integration = google_integration_for_user(g.user.id)
    if integration is None or integration.status != "connected":
        flash("Connect a calendar before syncing.", "error")
        return redirect(url_for("main.dashboard"))
    if integration.mode == "demo":
        cache_busy_periods(integration, demo_busy_periods(datetime.now(timezone.utc).date(), 14))
        db.session.commit()
        flash("Demo calendar availability updated.", "success")
    else:
        flash("Live calendar event retrieval is not enabled in this demo build.", "error")
    return redirect(url_for("main.dashboard"))


@main.post("/integrations/google-calendar/disconnect")
@login_required
def disconnect_google_calendar():
    session.pop("google_oauth_attempt", None)
    integration = google_integration_for_user(g.user.id)
    revocation_failed = False
    if integration is not None:
        if integration.mode == "live" and integration.credential:
            try:
                from .services.calendar import decrypt_token
                encrypted = (
                    integration.credential.encrypted_refresh_token
                    or integration.credential.encrypted_access_token
                )
                if encrypted:
                    oauth_client().revoke_token(decrypt_token(encrypted))
            except CalendarProviderError:
                revocation_failed = True
            db.session.delete(integration.credential)
        integration.mode = None
        integration.status = "disconnected"
        integration.provider_account_id = None
        integration.provider_account_email = None
        integration.granted_scopes = None
        integration.cached_payload = None
        integration.last_synced_at = None
        integration.last_error_code = None
        integration.retry_count = 0
        db.session.commit()
    if revocation_failed:
        flash("Calendar disconnected locally, but Google could not be reached to confirm revocation.", "success")
    else:
        flash("Calendar disconnected.", "success")
    return redirect(url_for("main.dashboard"))


def _time_window_errors(starts_at_time, ends_at_time):
    if ends_at_time <= starts_at_time:
        return "End time must be after start time."
    return None


@main.post("/availability/weekly")
@login_required
def add_weekly_availability():
    try:
        weekday = int(request.form.get("weekday", ""))
        starts_at_time = parse_time(request.form.get("starts_at_time", ""))
        ends_at_time = parse_time(request.form.get("ends_at_time", ""))
    except (TypeError, ValueError):
        flash("Enter a valid weekday, start time, and end time.", "error")
        return redirect(url_for("main.availability_page"))
    if weekday not in range(7):
        flash("Choose a valid weekday.", "error")
        return redirect(url_for("main.availability_page"))
    error = _time_window_errors(starts_at_time, ends_at_time)
    if error:
        flash(error, "error")
        return redirect(url_for("main.availability_page"))
    db.session.add(WeeklyAvailability(
        user_id=g.user.id,
        weekday=weekday,
        starts_at_time=starts_at_time,
        ends_at_time=ends_at_time,
        label=request.form.get("label", "").strip()[:120],
    ))
    db.session.commit()
    flash("Weekly study window added.", "success")
    return redirect(url_for("main.availability_page"))


@main.post("/availability/overrides")
@login_required
def add_availability_override():
    try:
        override_date = parse_date(request.form.get("date", ""))
        starts_at_time = parse_time(request.form.get("starts_at_time", ""))
        ends_at_time = parse_time(request.form.get("ends_at_time", ""))
    except (TypeError, ValueError):
        flash("Enter a valid date, start time, and end time.", "error")
        return redirect(url_for("main.availability_page"))
    mode = request.form.get("mode")
    if mode not in {"available", "unavailable"}:
        flash("Choose whether this adds availability or blocks time.", "error")
        return redirect(url_for("main.availability_page"))
    error = _time_window_errors(starts_at_time, ends_at_time)
    if error:
        flash(error, "error")
        return redirect(url_for("main.availability_page"))
    db.session.add(AvailabilityOverride(
        user_id=g.user.id,
        date=override_date,
        starts_at_time=starts_at_time,
        ends_at_time=ends_at_time,
        mode=mode,
        label=request.form.get("label", "").strip()[:120],
    ))
    db.session.commit()
    flash("Schedule exception saved.", "success")
    return redirect(url_for("main.availability_page"))


@main.get("/api/focus-sessions/active")
@api_login_required
def active_focus_session_api():
    focus_session = active_focus_for_user(g.user.id)
    return jsonify(session=focus_payload(focus_session) if focus_session else None)


@main.get("/api/focus-sessions/history")
@api_login_required
def focus_session_history_api():
    return jsonify(sessions=[focus_payload(item) for item in recent_focus_history(g.user.id)])


@main.get("/api/focus-sessions/<int:focus_session_id>")
@api_login_required
def focus_session_detail_api(focus_session_id):
    focus_session = get_owned_record(FocusSession, focus_session_id)
    return jsonify(session=focus_payload(focus_session)) if focus_session else api_not_found()


@main.post("/api/focus-sessions")
@api_login_required
def start_focus_session_api():
    data = request.get_json(silent=True) or {}
    assignment_id = data.get("assignment_id")
    planned_minutes = data.get("planned_minutes")
    if not isinstance(assignment_id, int) or isinstance(assignment_id, bool):
        return jsonify(error="A valid assignment ID is required."), 400
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        return api_not_found()
    try:
        focus_session = start_focus_session(g.user.id, assignment, planned_minutes)
    except FocusStateError as exc:
        status = 409 if active_focus_for_user(g.user.id) else 400
        return jsonify(error=str(exc)), status
    return jsonify(session=focus_payload(focus_session)), 201


def _owned_focus_or_error(focus_session_id):
    focus_session = get_owned_record(FocusSession, focus_session_id)
    if focus_session is None:
        return None, api_not_found()
    return focus_session, None


@main.post("/api/focus-sessions/<int:focus_session_id>/pause")
@api_login_required
def pause_focus_session_api(focus_session_id):
    focus_session, error = _owned_focus_or_error(focus_session_id)
    if error:
        return error
    try:
        pause_focus_session(focus_session)
    except FocusStateError as exc:
        return jsonify(error=str(exc)), 409
    return jsonify(session=focus_payload(focus_session))


@main.post("/api/focus-sessions/<int:focus_session_id>/resume")
@api_login_required
def resume_focus_session_api(focus_session_id):
    focus_session, error = _owned_focus_or_error(focus_session_id)
    if error:
        return error
    try:
        resume_focus_session(focus_session)
    except FocusStateError as exc:
        return jsonify(error=str(exc)), 409
    return jsonify(session=focus_payload(focus_session))


@main.post("/api/focus-sessions/<int:focus_session_id>/end")
@api_login_required
def end_focus_session_api(focus_session_id):
    focus_session, error = _owned_focus_or_error(focus_session_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        end_focus_session(focus_session, timer_complete=data.get("reason") == "timer_complete")
    except FocusStateError as exc:
        return jsonify(error=str(exc)), 409
    return jsonify(session=focus_payload(focus_session), assignments=ranked_active_assignments_payload())


@main.route("/assignments/new", methods=("GET", "POST"))
@login_required
def new_assignment():
    errors = {}
    form_data = {}
    if request.method == "POST":
        form_data = request.form.to_dict()
        assignment, errors = create_assignment(g.user.id, request.form)
        if assignment:
            flash(f'"{assignment.title}" was added to your plan.', "success")
            if assignment.completed:
                return redirect(url_for("main.dashboard"))
            return redirect(url_for("main.schedule_assignment", assignment_id=assignment.id))
    status = 400 if errors else 200
    return render_template("assignment_form.html", errors=errors, form_data=form_data, mode="create"), status


@main.route("/assignments/<int:assignment_id>/edit", methods=("GET", "POST"))
@login_required
def edit_assignment(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        abort(404)

    errors = {}
    if request.method == "POST":
        form_data = request.form.to_dict()
        updated, errors = save_assignment_updates(assignment, request.form)
        if updated:
            flash(f'"{updated.title}" was updated.', "success")
            return redirect(url_for("main.dashboard"))
        return render_template("assignment_form.html", assignment=assignment, errors=errors, form_data=form_data, mode="edit"), 400

    form_data = {
        "title": assignment.title,
        "course": assignment.course,
        "deadline": assignment.deadline.strftime("%Y-%m-%dT%H:%M"),
        "difficulty": assignment.difficulty,
        "estimated_minutes": assignment.estimated_minutes,
        "course_impact": assignment.course_impact,
        "progress": assignment.progress,
        "completed": assignment.completed,
        "notes": assignment.notes,
        "provider_id": assignment.provider_id or "",
    }
    return render_template("assignment_form.html", assignment=assignment, errors=errors, form_data=form_data, mode="edit")


@main.post("/assignments/<int:assignment_id>/delete")
@login_required
def delete_assignment_page(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        abort(404)
    title = assignment.title
    remove_assignment(assignment)
    flash(f'"{title}" was deleted from your plan.', "success")
    return redirect(url_for("main.dashboard"))


@main.post("/assignments/<int:assignment_id>/progress")
@login_required
def update_assignment_progress(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        abort(404)

    action = request.form.get("action", "save_progress")
    if action == "mark_complete":
        updated, errors = set_assignment_status(assignment, progress=100, completed=True)
        success_message = f'"{assignment.title}" was marked complete.'
    elif action == "mark_incomplete":
        updated, errors = set_assignment_status(assignment, completed=False)
        success_message = f'"{assignment.title}" is back in your active queue.'
    elif action == "save_progress":
        try:
            progress = int(request.form.get("progress", ""))
        except (TypeError, ValueError):
            progress = None
        if progress is None:
            updated, errors = None, {"progress": "Progress must be a whole number from 0 to 100."}
        else:
            updated, errors = set_assignment_status(assignment, progress=progress)
        success_message = f'Progress for "{assignment.title}" was updated.'
    else:
        updated, errors = None, {"action": "Unknown progress action."}

    if errors:
        flash(next(iter(errors.values())), "error")
    else:
        flash(success_message, "success")
    return redirect(url_for("main.dashboard"))


@main.get("/assignments/<int:assignment_id>")
@login_required
def assignment_detail(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        abort(404)
    return render_template("assignment_detail.html", assignment=assignment)


@main.route("/assignments/<int:assignment_id>/schedule", methods=("GET", "POST"))
@login_required
def schedule_assignment(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        abort(404)
    dismissed = db.session.scalar(
        owned_records(ScheduledFocusBlock)
        .where(
            ScheduledFocusBlock.assignment_id == assignment.id,
            ScheduledFocusBlock.status == "dismissed",
        )
        .order_by(ScheduledFocusBlock.id.desc())
    )
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "dismiss":
            if dismissed is None:
                db.session.add(ScheduledFocusBlock(
                    user_id=g.user.id,
                    assignment_id=assignment.id,
                    status="dismissed",
                    source="dismissed",
                    note="User dismissed scheduling suggestions.",
                ))
                db.session.commit()
            flash("Scheduling suggestions dismissed for this assignment.", "success")
            return redirect(url_for("main.dashboard"))

        if action in {"accept", "adjust"}:
            try:
                starts_at = request.form.get("starts_at", "").strip()
                if "T" in starts_at:
                    starts_at = starts_at + ":00" if starts_at.count(":") == 1 else starts_at
                starts_at = datetime.fromisoformat(starts_at)
                planned_minutes = int(request.form.get("planned_minutes", ""))
            except (TypeError, ValueError):
                flash("Choose a valid start time and duration.", "error")
                return redirect(url_for("main.schedule_assignment", assignment_id=assignment.id))
            confirm_transition = request.form.get("confirm_transition") == "1"
            block_range, errors, warnings, focus_conflicts = validate_scheduled_block(
                assignment,
                g.user,
                starts_at,
                planned_minutes,
                confirm_transition=confirm_transition,
                calendar_conflicts=calendar_conflicts_for_user(g.user.id, starts_at.date(), 1),
            )
            if focus_conflicts:
                non_conflict_errors = [
                    error for error in errors
                    if not error.startswith("This overlaps an existing study block.")
                ]
                resolution = request.form.get("conflict_resolution", "")
                if resolution == "keep_current_plan":
                    flash("Your current schedule was kept unchanged.", "success")
                    return redirect(url_for("main.dashboard"))
                if resolution and non_conflict_errors:
                    for error in non_conflict_errors:
                        flash(error, "error")
                    return redirect(url_for("main.schedule_assignment", assignment_id=assignment.id))
                if resolution == "replace_existing":
                    for conflict in focus_conflicts:
                        block = db.session.get(ScheduledFocusBlock, conflict.focus_block_id)
                        if block and block.user_id == g.user.id:
                            block.status = "cancelled"
                    db.session.add(ScheduledFocusBlock(
                        user_id=g.user.id,
                        assignment_id=assignment.id,
                        starts_at=block_range[0],
                        ends_at=block_range[1],
                        planned_minutes=planned_minutes,
                        status="scheduled",
                        source="replacement",
                    ))
                    db.session.commit()
                    flash("Existing study block replaced.", "success")
                    return redirect(url_for("main.dashboard"))
                if resolution == "combine":
                    combined_start = min([block_range[0], *[conflict.starts_at for conflict in focus_conflicts]])
                    combined_end = max([block_range[1], *[conflict.ends_at for conflict in focus_conflicts]])
                    combined_minutes = min(int((combined_end - combined_start).total_seconds() // 60), 240)
                    for conflict in focus_conflicts:
                        block = db.session.get(ScheduledFocusBlock, conflict.focus_block_id)
                        if block and block.user_id == g.user.id:
                            block.status = "cancelled"
                    db.session.add(ScheduledFocusBlock(
                        user_id=g.user.id,
                        assignment_id=assignment.id,
                        starts_at=combined_start,
                        ends_at=combined_start + timedelta(minutes=combined_minutes),
                        planned_minutes=combined_minutes,
                        status="scheduled",
                        source="combined",
                        note="Combined with an overlapping study block.",
                    ))
                    db.session.commit()
                    flash("Study blocks combined.", "success")
                    return redirect(url_for("main.dashboard"))
                if resolution == "reschedule_existing":
                    old_blocks = []
                    for conflict in focus_conflicts:
                        block = db.session.get(ScheduledFocusBlock, conflict.focus_block_id)
                        if block and block.user_id == g.user.id:
                            block.status = "rescheduled"
                            old_blocks.append(block)
                    db.session.add(ScheduledFocusBlock(
                        user_id=g.user.id,
                        assignment_id=assignment.id,
                        starts_at=block_range[0],
                        ends_at=block_range[1],
                        planned_minutes=planned_minutes,
                        status="scheduled",
                        source="replacement",
                    ))
                    db.session.flush()
                    for block in old_blocks:
                        old_assignment = db.session.get(Assignment, block.assignment_id)
                        if old_assignment:
                            old_recommendation = calendar_recommendation(old_assignment, start_day=block_range[1].date(), days=7)
                            if old_recommendation.suggestions:
                                suggestion = old_recommendation.suggestions[0]
                                db.session.add(ScheduledFocusBlock(
                                    user_id=g.user.id,
                                    assignment_id=old_assignment.id,
                                    starts_at=suggestion.starts_at,
                                    ends_at=suggestion.ends_at,
                                    planned_minutes=suggestion.planned_minutes,
                                    status="scheduled",
                                    source="rescheduled",
                                    note="Moved to make room for a higher-priority block.",
                                ))
                    db.session.commit()
                    flash("Existing study block rescheduled where space was available.", "success")
                    return redirect(url_for("main.dashboard"))
                return render_template(
                    "schedule_assignment.html",
                    assignment=assignment,
                    recommendation=calendar_recommendation(assignment),
                    calendar_status=calendar_status_for_user(g.user.id),
                    dismissed=dismissed,
                    errors=errors,
                    warnings=warnings,
                    focus_conflicts=focus_conflicts,
                    proposed_start=starts_at,
                    proposed_minutes=planned_minutes,
                ), 409
            if errors:
                for error in errors:
                    flash(error, "error")
                return redirect(url_for("main.schedule_assignment", assignment_id=assignment.id))
            if warnings:
                return render_template(
                    "schedule_assignment.html",
                    assignment=assignment,
                    recommendation=calendar_recommendation(assignment),
                    calendar_status=calendar_status_for_user(g.user.id),
                    dismissed=dismissed,
                    errors=[],
                    warnings=warnings,
                    focus_conflicts=[],
                    proposed_start=starts_at,
                    proposed_minutes=planned_minutes,
                ), 409
            db.session.add(ScheduledFocusBlock(
                user_id=g.user.id,
                assignment_id=assignment.id,
                starts_at=block_range[0],
                ends_at=block_range[1],
                planned_minutes=planned_minutes,
                status="scheduled",
                source="adjusted" if action == "adjust" else "recommended",
            ))
            db.session.commit()
            flash("Focus block scheduled.", "success")
            return redirect(url_for("main.dashboard"))

        flash("Choose a scheduling action.", "error")
        return redirect(url_for("main.schedule_assignment", assignment_id=assignment.id))

    return render_template(
        "schedule_assignment.html",
        assignment=assignment,
        recommendation=calendar_recommendation(assignment),
        calendar_status=calendar_status_for_user(g.user.id),
        dismissed=dismissed,
        errors=[],
        warnings=[],
        focus_conflicts=[],
        proposed_start=None,
        proposed_minutes=None,
    )


@main.post("/scheduled-focus-blocks/<int:block_id>/start")
@login_required
def start_scheduled_focus_block(block_id):
    block = get_owned_record(ScheduledFocusBlock, block_id)
    if block is None or block.status != "scheduled":
        abort(404)
    assignment = get_owned_record(Assignment, block.assignment_id)
    if assignment is None:
        abort(404)
    try:
        start_focus_session(g.user.id, assignment, block.planned_minutes)
    except FocusStateError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.dashboard"))
    block.status = "completed"
    db.session.commit()
    flash(f'Focus block for "{assignment.title}" started.', "success")
    return redirect(url_for("main.dashboard"))


@main.get("/api/assignments/<int:assignment_id>")
@api_login_required
def assignment_api_detail(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    return jsonify(assignment_payload(assignment)) if assignment else api_not_found()


@main.patch("/api/assignments/<int:assignment_id>")
@api_login_required
def update_assignment(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        return api_not_found()

    data = request.get_json(silent=True) or {}
    if "progress" in data:
        if isinstance(data["progress"], bool) or not isinstance(data["progress"], int) or not 0 <= data["progress"] <= 100:
            return jsonify(error="Progress must be an integer from 0 to 100."), 400
        assignment.progress = data["progress"]
    if "completed" in data:
        if not isinstance(data["completed"], bool):
            return jsonify(error="Completed must be true or false."), 400
        assignment.completed = data["completed"]
    db.session.commit()
    return jsonify(**assignment_payload(assignment), assignments=ranked_active_assignments_payload())


@main.delete("/api/assignments/<int:assignment_id>")
@api_login_required
def delete_assignment(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        return api_not_found()
    remove_assignment(assignment)
    return "", 204


@main.get("/api/integrations/<int:integration_id>")
@api_login_required
def integration_api_detail(integration_id):
    integration = get_owned_record(IntegrationState, integration_id)
    return jsonify(integration_payload(integration)) if integration else api_not_found()


@main.patch("/api/integrations/<int:integration_id>")
@api_login_required
def update_integration(integration_id):
    integration = get_owned_record(IntegrationState, integration_id)
    if integration is None:
        return api_not_found()
    data = request.get_json(silent=True) or {}
    allowed_statuses = {"connected", "disconnected", "error"}
    if data.get("status") not in allowed_statuses:
        return jsonify(error="Status must be connected, disconnected, or error."), 400
    integration.status = data["status"]
    db.session.commit()
    return jsonify(integration_payload(integration))


@main.delete("/api/integrations/<int:integration_id>")
@api_login_required
def delete_integration(integration_id):
    integration = get_owned_record(IntegrationState, integration_id)
    if integration is None:
        return api_not_found()
    db.session.delete(integration)
    db.session.commit()
    return "", 204


@main.get("/api/health")
def health():
    return jsonify(status="ok", app="PlanGuard")
