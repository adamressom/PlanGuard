from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from . import db
from .auth import api_login_required, login_required
from .models import Assignment, FocusSession, IntegrationState
from .services.assignments import create_assignment, remove_assignment, set_assignment_status, update_assignment as save_assignment_updates
from .services.focus import FocusStateError, active_focus_for_user, end_focus_session, focus_payload, pause_focus_session, recent_focus_history, resume_focus_session, start_focus_session
from .services.ownership import get_owned_record, owned_records
from .services.priority import assignment_priority_input, rank_assignments

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
        "status": integration.status,
        "last_synced_at": integration.last_synced_at.isoformat() if integration.last_synced_at else None,
        "retry_count": integration.retry_count,
    }


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
            return redirect(url_for("main.dashboard"))
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
