from datetime import datetime

from .. import db
from ..models import Assignment


def _required_text(data, field, label, max_length, errors):
    value = str(data.get(field, "")).strip()
    if not value:
        errors[field] = f"{label} is required."
    elif len(value) > max_length:
        errors[field] = f"{label} must be {max_length} characters or fewer."
    return value


def _integer_in_range(data, field, label, minimum, maximum, errors, default=None):
    raw_value = data.get(field, "")
    if raw_value in (None, "") and default is not None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        errors[field] = f"{label} must be a whole number from {minimum} to {maximum}."
        return minimum
    if not minimum <= value <= maximum:
        errors[field] = f"{label} must be from {minimum} to {maximum}."
    return value


def _float_in_range(data, field, label, minimum, maximum, errors):
    try:
        value = float(data.get(field, ""))
    except (TypeError, ValueError):
        errors[field] = f"{label} must be a number from {minimum} to {maximum}."
        return float(minimum)
    if not minimum <= value <= maximum:
        errors[field] = f"{label} must be from {minimum} to {maximum}."
    return value


def validate_assignment(data):
    errors = {}
    values = {
        "title": _required_text(data, "title", "Title", 180, errors),
        "course": _required_text(data, "course", "Course", 120, errors),
        "difficulty": _integer_in_range(data, "difficulty", "Difficulty", 1, 5, errors),
        "estimated_minutes": _integer_in_range(data, "estimated_minutes", "Estimated minutes", 1, 1440, errors),
        "course_weight": _float_in_range(data, "course_impact", "Course impact", 0, 100, errors),
        "progress": _integer_in_range(data, "progress", "Progress", 0, 100, errors, default=0),
        "completed": str(data.get("completed", "")).lower() in {"1", "true", "on", "yes"},
    }

    deadline_text = str(data.get("deadline", "")).strip()
    if not deadline_text:
        errors["deadline"] = "Deadline is required."
        values["deadline"] = None
    else:
        try:
            values["deadline"] = datetime.fromisoformat(deadline_text)
        except ValueError:
            errors["deadline"] = "Enter a valid deadline."
            values["deadline"] = None

    notes = str(data.get("notes", "")).strip()
    provider_id = str(data.get("provider_id", "")).strip()
    if len(notes) > 5000:
        errors["notes"] = "Notes must be 5000 characters or fewer."
    if len(provider_id) > 255:
        errors["provider_id"] = "Provider ID must be 255 characters or fewer."
    values["notes"] = notes
    values["provider_id"] = provider_id or None
    return values, errors


def create_assignment(user_id, data):
    values, errors = validate_assignment(data)
    if errors:
        return None, errors
    assignment = Assignment(user_id=user_id, **values)
    db.session.add(assignment)
    db.session.commit()
    return assignment, {}
