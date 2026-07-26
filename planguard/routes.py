from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, render_template, request, session

from .services.assignments import (
    AssignmentNotFoundError,
    InvalidProgressError,
    require_assignment,
    update_assignment_progress,
)
from .services.priority import rank_assignments

main = Blueprint("main", __name__)


def demo_assignments():
    now = datetime.now(timezone.utc)
    # Future database-backed assignments can include completed status, and
    # focus sessions can track assignment_id, started_at, and ended_at separately.
    return [
        {"id": "physics-problem-set", "title": "Physics problem set", "course": "PHYS 201", "deadline": now + timedelta(hours=18), "difficulty": 4, "estimated_minutes": 110, "course_weight": 18, "progress": 20},
        {"id": "history-research-outline", "title": "History research outline", "course": "HIST 140", "deadline": now + timedelta(days=2), "difficulty": 3, "estimated_minutes": 75, "course_weight": 25, "progress": 5},
        {"id": "calculus-quiz-review", "title": "Calculus quiz review", "course": "MATH 220", "deadline": now + timedelta(days=1), "difficulty": 5, "estimated_minutes": 50, "course_weight": 10, "progress": 55},
    ]


def get_assignments_for_dashboard():
    """Return assignments in the dashboard-ready dictionary shape."""
    progress_overrides = session.get("assignment_progress", {})
    return [
        {
            **assignment,
            "progress": progress_overrides.get(assignment["id"], assignment["progress"]),
        }
        for assignment in demo_assignments()
    ]


@main.get("/")
def landing():
    return render_template("landing.html")


@main.get("/dashboard")
def dashboard():
    assignments = rank_assignments(get_assignments_for_dashboard())
    # Future: when assignments are user-created, handle the empty state
    # before reading assignments[0] for the recommended focus card.
    return render_template("dashboard.html", assignments=assignments, recommended=assignments[0])


@main.get("/api/health")
def health():
    return jsonify(status="ok", app="PlanGuard")


@main.post("/api/focus-sessions/end")
def end_focus_session():
    payload = request.get_json(silent=True) or {}
    assignment_id = payload.get("assignment_id")
    assignments = get_assignments_for_dashboard()

    if "progress" not in payload or payload.get("progress") in (None, ""):
        try:
            ranked = rank_assignments(require_assignment(assignments, assignment_id))
        except AssignmentNotFoundError:
            return jsonify(error="Assignment not found."), 400

        return jsonify(assignments=ranked, progress_updated=False)

    try:
        ranked = update_assignment_progress(assignments, assignment_id, payload["progress"])
    except AssignmentNotFoundError:
        return jsonify(error="Assignment not found."), 400
    except InvalidProgressError:
        return jsonify(error="Progress must be a number."), 400

    progress_by_assignment = dict(session.get("assignment_progress", {}))
    progress_by_assignment[assignment_id] = next(
        item["progress"] for item in ranked if item["id"] == assignment_id
    )
    session["assignment_progress"] = progress_by_assignment

    return jsonify(assignments=ranked, progress_updated=True)

