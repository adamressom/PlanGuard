from datetime import datetime, timezone


def calculate_priority(assignment, available_minutes=120, now=None):
    """Return a normalized 0-100 urgency score.

    The weights are intentionally visible and easy to tune during the hackathon.
    """
    now = now or datetime.now(timezone.utc)
    deadline = assignment["deadline"]
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    hours_left = max((deadline - now).total_seconds() / 3600, 0)
    urgency = max(0, 40 - min(hours_left, 168) / 168 * 40)
    difficulty = min(max(assignment.get("difficulty", 3), 1), 5) / 5 * 20
    weight = min(max(assignment.get("course_weight", 10), 0), 100) / 100 * 25
    estimated = max(assignment.get("estimated_minutes", 60), 1)
    fit = min(available_minutes / estimated, 1) * 10
    progress_penalty = min(max(assignment.get("progress", 0), 0), 100) / 100 * 15
    return round(min(max(urgency + difficulty + weight + fit - progress_penalty, 0), 100), 1)


def rank_assignments(assignments, available_minutes=120, now=None):
    scored = [
        {**item, "priority_score": calculate_priority(item, available_minutes, now)}
        for item in assignments
    ]
    return sorted(scored, key=lambda item: item["priority_score"], reverse=True)

