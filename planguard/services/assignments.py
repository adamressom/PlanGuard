from .priority import rank_assignments


class AssignmentProgressError(ValueError):
    """Base error for assignment progress update failures."""


class AssignmentNotFoundError(AssignmentProgressError):
    """Raised when an assignment ID does not match any assignment."""


class InvalidProgressError(AssignmentProgressError):
    """Raised when progress cannot be parsed as a number."""


def clamp_progress(progress):
    try:
        value = int(progress)
    except (TypeError, ValueError) as exc:
        raise InvalidProgressError("Progress must be a number.") from exc

    return min(max(value, 0), 100)


def require_assignment(assignments, assignment_id):
    if not any(assignment["id"] == assignment_id for assignment in assignments):
        raise AssignmentNotFoundError("Assignment not found.")

    return assignments


def update_assignment_progress(assignments, assignment_id, progress, available_minutes=120, now=None):
    updated_progress = clamp_progress(progress)
    found_assignment = False
    updated_assignments = []

    for assignment in assignments:
        if assignment["id"] == assignment_id:
            found_assignment = True
            updated_assignments.append({**assignment, "progress": updated_progress})
        else:
            updated_assignments.append(assignment)

    if not found_assignment:
        raise AssignmentNotFoundError("Assignment not found.")

    return rank_assignments(updated_assignments, available_minutes=available_minutes, now=now)
