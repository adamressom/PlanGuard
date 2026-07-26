from datetime import datetime, timezone

from .. import db
from ..models import FocusSession

ACTIVE_FOCUS_STATUSES = ("running", "paused")
HISTORY_FOCUS_STATUSES = ("completed", "ended")


class FocusStateError(ValueError):
    pass


def _aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_now():
    return datetime.now(timezone.utc)


def elapsed_seconds(session, now=None):
    now = _aware(now) or utc_now()
    elapsed = max(int(session.accumulated_seconds or 0), 0)
    if session.status == "running" and session.last_resumed_at:
        elapsed += max(int((now - _aware(session.last_resumed_at)).total_seconds()), 0)
    return elapsed


def remaining_seconds(session, now=None):
    return max(session.planned_minutes * 60 - elapsed_seconds(session, now), 0)


def focus_payload(session, now=None):
    now = _aware(now) or utc_now()
    elapsed = elapsed_seconds(session, now)
    remaining = max(session.planned_minutes * 60 - elapsed, 0)
    return {
        "id": session.id,
        "assignment_id": session.assignment_id,
        "assignment_title": session.assignment_title,
        "planned_minutes": session.planned_minutes,
        "status": session.status,
        "elapsed_seconds": elapsed,
        "completed_seconds": session.completed_seconds,
        "remaining_seconds": remaining,
        "started_at": _aware(session.started_at).isoformat(),
        "ended_at": _aware(session.ended_at).isoformat() if session.ended_at else None,
        "server_now": now.isoformat(),
    }


def active_focus_for_user(user_id):
    return db.session.scalar(
        db.select(FocusSession)
        .where(FocusSession.user_id == user_id, FocusSession.status.in_(ACTIVE_FOCUS_STATUSES))
        .order_by(FocusSession.id.desc())
    )


def recent_focus_history(user_id, limit=5):
    return db.session.scalars(
        db.select(FocusSession)
        .where(FocusSession.user_id == user_id, FocusSession.status.in_(HISTORY_FOCUS_STATUSES))
        .order_by(FocusSession.ended_at.desc(), FocusSession.id.desc())
        .limit(limit)
    ).all()


def start_focus_session(user_id, assignment, planned_minutes, now=None):
    if active_focus_for_user(user_id):
        raise FocusStateError("End the current focus session before starting another one.")
    if isinstance(planned_minutes, bool) or not isinstance(planned_minutes, int) or not 1 <= planned_minutes <= 240:
        raise FocusStateError("Focus duration must be a whole number from 1 to 240 minutes.")
    if assignment.completed:
        raise FocusStateError("Completed assignments cannot start a focus session.")

    now = _aware(now) or utc_now()
    session = FocusSession(
        user_id=user_id,
        assignment_id=assignment.id,
        assignment_title=assignment.title,
        planned_minutes=planned_minutes,
        status="running",
        accumulated_seconds=0,
        started_at=now,
        last_resumed_at=now,
    )
    db.session.add(session)
    db.session.commit()
    return session


def pause_focus_session(session, now=None):
    if session.status != "running":
        raise FocusStateError("Only a running focus session can be paused.")
    now = _aware(now) or utc_now()
    session.accumulated_seconds = elapsed_seconds(session, now)
    session.last_resumed_at = None
    session.status = "paused"
    db.session.commit()
    return session


def resume_focus_session(session, now=None):
    if session.status != "paused":
        raise FocusStateError("Only a paused focus session can be resumed.")
    now = _aware(now) or utc_now()
    session.last_resumed_at = now
    session.status = "running"
    db.session.commit()
    return session


def end_focus_session(session, timer_complete=False, now=None):
    if session.status not in ACTIVE_FOCUS_STATUSES:
        raise FocusStateError("This focus session has already ended.")
    now = _aware(now) or utc_now()
    if session.status == "running":
        session.accumulated_seconds = elapsed_seconds(session, now)
    session.accumulated_seconds = min(session.accumulated_seconds, session.planned_minutes * 60)
    session.completed_seconds = session.accumulated_seconds
    session.last_resumed_at = None
    session.ended_at = now
    session.status = "completed" if timer_complete or session.accumulated_seconds >= session.planned_minutes * 60 else "ended"
    db.session.commit()
    return session
