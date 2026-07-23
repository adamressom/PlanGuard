from flask import Blueprint, abort, jsonify, render_template, request

from . import db
from .auth import api_login_required, login_required
from .models import Assignment, IntegrationState
from .services.ownership import get_owned_record, owned_records
from .services.priority import rank_assignments

main = Blueprint("main", __name__)


def assignment_payload(assignment):
    return {
        "id": assignment.id,
        "title": assignment.title,
        "course": assignment.course,
        "deadline": assignment.deadline.isoformat(),
        "difficulty": assignment.difficulty,
        "estimated_minutes": assignment.estimated_minutes,
        "course_weight": assignment.course_weight,
        "progress": assignment.progress,
        "completed": assignment.completed,
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
    records = db.session.scalars(owned_records(Assignment)).all()
    assignments = rank_assignments([
        {
            "id": item.id,
            "title": item.title,
            "course": item.course,
            "deadline": item.deadline,
            "difficulty": item.difficulty,
            "estimated_minutes": item.estimated_minutes,
            "course_weight": item.course_weight,
            "progress": item.progress,
        }
        for item in records
    ])
    return render_template("dashboard.html", assignments=assignments)


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
