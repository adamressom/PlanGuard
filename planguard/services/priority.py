from datetime import datetime, timedelta, timezone
from math import isfinite


def _as_number(value, default):
    try:
        number = float(value)
        return number if isfinite(number) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _aware_datetime(value):
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now_utc(now=None):
    return _aware_datetime(now) or datetime.now(timezone.utc)


def deadline_metadata(deadline, now=None):
    now = _now_utc(now)
    deadline = _aware_datetime(deadline)
    if deadline is None:
        return {
            "is_overdue": False,
            "deadline_status": "missing",
            "due_label": "No deadline",
            "hours_overdue": 0,
        }

    seconds_left = (deadline - now).total_seconds()
    if seconds_left < 0:
        hours_overdue = abs(seconds_left) / 3600
        if hours_overdue < 1:
            label = "Overdue by less than 1 hour"
        elif hours_overdue < 48:
            label = f"Overdue by {max(1, round(hours_overdue))}h"
        else:
            label = f"Overdue by {max(2, round(hours_overdue / 24))}d"
        return {
            "is_overdue": True,
            "deadline_status": "overdue",
            "due_label": label,
            "hours_overdue": round(hours_overdue, 1),
        }

    hours_left = seconds_left / 3600
    if hours_left < 1:
        label = "Due in less than 1 hour"
    elif hours_left < 48:
        label = f"Due in {max(1, round(hours_left))}h"
    else:
        label = f"Due in {max(2, round(hours_left / 24))}d"
    return {
        "is_overdue": False,
        "deadline_status": "upcoming",
        "due_label": label,
        "hours_overdue": 0,
    }


def calculate_priority(assignment, available_minutes=120, now=None):
    """Return a deterministic, normalized 0–100 priority score."""
    now = _now_utc(now)
    deadline = _aware_datetime(assignment.get("deadline"))

    if deadline is None:
        urgency = 0
    else:
        hours_left = (deadline - now).total_seconds() / 3600
        if hours_left < 0:
            overdue_bonus = min(abs(hours_left) / 168 * 10, 10)
            urgency = 40 + overdue_bonus
        else:
            urgency = max(0, 40 - min(hours_left, 168) / 168 * 40)

    difficulty_value = min(max(_as_number(assignment.get("difficulty"), 3), 1), 5)
    difficulty = difficulty_value / 5 * 20
    course_weight = min(max(_as_number(assignment.get("course_weight"), 10), 0), 100)
    weight = course_weight / 100 * 25
    estimated = max(_as_number(assignment.get("estimated_minutes"), 60), 1)
    available = max(_as_number(available_minutes, 120), 0)
    fit = min(available / estimated, 1) * 10
    progress = min(max(_as_number(assignment.get("progress"), 0), 0), 100)
    progress_penalty = progress / 100 * 15
    return round(min(max(urgency + difficulty + weight + fit - progress_penalty, 0), 100), 1)


def assignment_priority_input(assignment):
    """Translate a database model into the priority engine's stable input contract."""
    return {
        "id": assignment.id,
        "title": assignment.title or "Untitled assignment",
        "course": assignment.course or "No course",
        "deadline": assignment.deadline,
        "difficulty": assignment.difficulty,
        "estimated_minutes": assignment.estimated_minutes,
        "course_weight": assignment.course_weight,
        "progress": assignment.progress,
    }


def rank_assignments(assignments, available_minutes=120, now=None):
    now = _now_utc(now)
    fallback_deadline = now + timedelta(days=36500)
    scored = []
    for position, item in enumerate(assignments):
        metadata = deadline_metadata(item.get("deadline"), now)
        scored.append({
            **item,
            **metadata,
            "priority_score": calculate_priority(item, available_minutes, now),
            "_sort_deadline": _aware_datetime(item.get("deadline")) or fallback_deadline,
            "_stable_position": position,
        })

    scored.sort(key=lambda item: (
        -item["priority_score"],
        item["_sort_deadline"],
        str(item.get("id", "")),
        item["_stable_position"],
    ))
    for item in scored:
        item.pop("_sort_deadline")
        item.pop("_stable_position")
    return scored
