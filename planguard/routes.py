from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, render_template

from .services.priority import rank_assignments

main = Blueprint("main", __name__)


def demo_assignments():
    now = datetime.now(timezone.utc)
    return [
        {"title": "Physics problem set", "course": "PHYS 201", "deadline": now + timedelta(hours=18), "difficulty": 4, "estimated_minutes": 110, "course_weight": 18, "progress": 20},
        {"title": "History research outline", "course": "HIST 140", "deadline": now + timedelta(days=2), "difficulty": 3, "estimated_minutes": 75, "course_weight": 25, "progress": 5},
        {"title": "Calculus quiz review", "course": "MATH 220", "deadline": now + timedelta(days=1), "difficulty": 5, "estimated_minutes": 50, "course_weight": 10, "progress": 55},
    ]


@main.get("/")
def landing():
    return render_template("landing.html")


@main.get("/dashboard")
def dashboard():
    assignments = rank_assignments(demo_assignments())
    return render_template("dashboard.html", assignments=assignments)


@main.get("/api/health")
def health():
    return jsonify(status="ok", app="PlanGuard")

