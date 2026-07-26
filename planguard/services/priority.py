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
        return {"is_overdue": False, "deadline_status": "missing", "due_label": "No deadline", "hours_overdue": 0}

    seconds_left = (deadline - now).total_seconds()
    if seconds_left < 0:
        hours_overdue = abs(seconds_left) / 3600
        if hours_overdue < 1:
            label = "Overdue by less than 1 hour"
        elif hours_overdue < 48:
            label = f"Overdue by {max(1, round(hours_overdue))}h"
        else:
            label = f"Overdue by {max(2, round(hours_overdue / 24))}d"
        return {"is_overdue": True, "deadline_status": "overdue", "due_label": label, "hours_overdue": round(hours_overdue, 1)}

    hours_left = seconds_left / 3600
    if hours_left < 1:
        label = "Due in less than 1 hour"
    elif hours_left < 48:
        label = f"Due in {max(1, round(hours_left))}h"
    else:
        label = f"Due in {max(2, round(hours_left / 24))}d"
    return {"is_overdue": False, "deadline_status": "upcoming", "due_label": label, "hours_overdue": 0}


def explain_priority(assignment, available_minutes=120, now=None):
    """Return the exact score, factor contributions, and deterministic copy."""
    now = _now_utc(now)
    deadline = _aware_datetime(assignment.get("deadline"))
    deadline_info = deadline_metadata(deadline, now)

    if deadline is None:
        urgency = 0
    else:
        hours_left = (deadline - now).total_seconds() / 3600
        if hours_left < 0:
            urgency = 40 + min(abs(hours_left) / 168 * 10, 10)
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

    fits_available_time = estimated <= available
    if available == 0:
        time_fit_label = "No study time available"
    elif fits_available_time:
        time_fit_label = f"Fits your {round(available)}-minute window"
    else:
        time_fit_label = f"Needs {max(1, round(estimated - available))} more minutes"

    if deadline_info["deadline_status"] == "overdue":
        deadline_copy = f"{deadline_info['due_label']} creates maximum deadline urgency."
        deadline_reason = "the deadline is overdue"
    elif urgency >= 30:
        deadline_copy = f"{deadline_info['due_label']} makes the deadline highly urgent."
        deadline_reason = "the deadline is approaching quickly"
    elif urgency > 0:
        deadline_copy = f"{deadline_info['due_label']} adds moderate deadline urgency."
        deadline_reason = "the deadline is getting closer"
    else:
        deadline_copy = f"{deadline_info['due_label']} adds little deadline urgency."
        deadline_reason = "the deadline is not currently urgent"

    difficulty_display = f"{difficulty_value:g}/5"
    if difficulty_value >= 4:
        difficulty_reason = "the work is highly difficult"
        difficulty_copy = f"Difficulty {difficulty_display} substantially raises the score."
    elif difficulty_value >= 3:
        difficulty_reason = "the work has moderate difficulty"
        difficulty_copy = f"Difficulty {difficulty_display} adds a moderate contribution."
    else:
        difficulty_reason = "the work is relatively straightforward"
        difficulty_copy = f"Difficulty {difficulty_display} adds a smaller contribution."

    impact_display = f"{course_weight:g}%"
    if course_weight >= 40:
        impact_reason = "it has major course impact"
        impact_copy = f"A {impact_display} course impact strongly raises priority."
    elif course_weight >= 15:
        impact_reason = "it has meaningful course impact"
        impact_copy = f"A {impact_display} course impact moderately raises priority."
    else:
        impact_reason = "its course impact is limited"
        impact_copy = f"A {impact_display} course impact adds a smaller contribution."

    if available == 0:
        time_reason = "no study time is available"
        time_copy = "No available study time means this task receives no time-fit points."
    elif fits_available_time:
        time_reason = "it fits the available study window"
        time_copy = f"Its {estimated:g}-minute estimate fits within the {available:g}-minute window."
    else:
        time_reason = "it exceeds the available study window"
        time_copy = f"Its {estimated:g}-minute estimate exceeds the {available:g}-minute window."

    progress_display = f"{progress:g}% complete"
    if progress >= 70:
        progress_reason = "most of the work is already complete"
        progress_copy = f"At {progress_display}, existing progress substantially lowers priority."
    elif progress > 0:
        progress_reason = "existing progress reduces the remaining workload"
        progress_copy = f"At {progress_display}, existing progress slightly lowers priority."
    else:
        progress_reason = "none of the work is complete yet"
        progress_copy = "At 0% complete, there is no progress reduction."

    factors = [
        {"key": "deadline", "label": "Deadline urgency", "value": deadline_info["due_label"], "points": round(urgency, 1), "max_points": 50, "percent": round(urgency / 50 * 100, 1), "explanation": deadline_copy, "reason": deadline_reason},
        {"key": "difficulty", "label": "Difficulty", "value": difficulty_display, "points": round(difficulty, 1), "max_points": 20, "percent": round(difficulty / 20 * 100, 1), "explanation": difficulty_copy, "reason": difficulty_reason},
        {"key": "course_impact", "label": "Course impact", "value": impact_display, "points": round(weight, 1), "max_points": 25, "percent": round(weight / 25 * 100, 1), "explanation": impact_copy, "reason": impact_reason},
        {"key": "time_fit", "label": "Time fit", "value": time_fit_label, "points": round(fit, 1), "max_points": 10, "percent": round(fit / 10 * 100, 1), "explanation": time_copy, "reason": time_reason},
        {"key": "progress", "label": "Current progress", "value": progress_display, "points": round(-progress_penalty, 1), "max_points": 15, "percent": round(progress_penalty / 15 * 100, 1), "explanation": progress_copy, "reason": progress_reason},
    ]

    raw_score = urgency + difficulty + weight + fit - progress_penalty
    final_score = round(min(max(raw_score, 0), 100), 1)
    positive_factors = sorted(factors[:4], key=lambda factor: (-factor["points"], factor["key"]))
    first_reason, second_reason = positive_factors[0]["reason"], positive_factors[1]["reason"]
    if final_score >= 70:
        band = "high"
        summary = f"High priority because {first_reason} and {second_reason}."
    elif final_score >= 40:
        band = "medium"
        summary = f"Medium priority: {first_reason} matters most, while {progress_reason}."
    else:
        band = "low"
        low_reason = progress_reason if progress >= 50 else deadline_reason
        summary = f"Lower priority because {low_reason}; other work may need attention first."

    return {
        "final_score": final_score,
        "raw_score": round(raw_score, 1),
        "band": band,
        "summary": summary,
        "factors": factors,
        "fits_available_time": fits_available_time,
        "time_fit_label": time_fit_label,
    }


def calculate_priority(assignment, available_minutes=120, now=None):
    """Return a deterministic, normalized 0–100 priority score."""
    return explain_priority(assignment, available_minutes, now)["final_score"]


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
    available = max(_as_number(available_minutes, 120), 0)
    fallback_deadline = now + timedelta(days=36500)
    scored = []
    for position, item in enumerate(assignments):
        metadata = deadline_metadata(item.get("deadline"), now)
        details = explain_priority(item, available, now)
        scored.append({
            **item,
            **metadata,
            "available_minutes": round(available),
            "fits_available_time": details["fits_available_time"],
            "time_fit_label": details["time_fit_label"],
            "priority_score": details["final_score"],
            "priority_band": details["band"],
            "priority_explanation": details["summary"],
            "score_factors": details["factors"],
            "_sort_deadline": _aware_datetime(item.get("deadline")) or fallback_deadline,
            "_stable_position": position,
        })

    scored.sort(key=lambda item: (-item["priority_score"], item["_sort_deadline"], str(item.get("id", "")), item["_stable_position"]))
    for item in scored:
        item.pop("_sort_deadline")
        item.pop("_stable_position")
    return scored
