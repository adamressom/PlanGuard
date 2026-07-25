from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from . import db
from .auth import api_login_required, login_required
from .models import Assignment, IntegrationState
from .services.assignments import create_assignment, remove_assignment, set_assignment_status, update_assignment as save_assignment_updates
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
        [assignment_priority_input(item) for item in active_records]
    )
    return render_template(
        "dashboard.html",
        assignments=active_assignments,
        completed_assignments=completed_assignments,
        recommended=active_assignments[0] if active_assignments else None,
    )


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
        if not isinstance(data["progress"], int) or not 0 <= data["progress"] <= 100:
            return jsonify(error="Progress must be an integer from 0 to 100."), 400
        assignment.progress = data["progress"]
    if "completed" in data:
        if not isinstance(data["completed"], bool):
            return jsonify(error="Completed must be true or false."), 400
        assignment.completed = data["completed"]
    db.session.commit()
    return jsonify(assignment_payload(assignment))


@main.delete("/api/assignments/<int:assignment_id>")
@api_login_required
def delete_assignment(assignment_id):
    assignment = get_owned_record(Assignment, assignment_id)
    if assignment is None:
        return api_not_found()
    db.session.delete(assignment)
    db.session.commit()
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
