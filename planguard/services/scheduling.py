from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from .. import db
from ..models import Assignment, AvailabilityOverride, ScheduledFocusBlock, WeeklyAvailability
from .priority import assignment_priority_input, calculate_priority

MIN_BLOCK_MINUTES = 15
MAX_BLOCK_MINUTES = 90
TRANSITION_WARNING_MINUTES = 15
RESCHEDULE_SCORE_GAP = 10
SCHEDULED_BLOCK_STATUSES = ("scheduled",)


@dataclass(frozen=True)
class StudyWindow:
    starts_at: datetime
    ends_at: datetime
    label: str = ""

    @property
    def duration_minutes(self):
        return max(int((self.ends_at - self.starts_at).total_seconds() // 60), 0)


@dataclass(frozen=True)
class ScheduleConflict:
    starts_at: datetime
    ends_at: datetime
    title: str
    source: str = "calendar"
    assignment_id: int | None = None
    focus_block_id: int | None = None
    priority_score: float | None = None


@dataclass(frozen=True)
class FocusBlockSuggestion:
    assignment_id: int
    assignment_title: str
    starts_at: datetime
    ends_at: datetime
    planned_minutes: int
    warning: str = ""
    source: str = "recommended"


@dataclass(frozen=True)
class ScheduleRecommendation:
    assignment_id: int
    assignment_title: str
    requested_minutes: int
    scheduled_minutes: int
    is_partial: bool
    suggestions: list[FocusBlockSuggestion]
    reschedule_conflicts: list[ScheduleConflict]


def aware_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def combine(day, clock):
    return datetime.combine(day, clock).replace(tzinfo=timezone.utc)


def ranges_overlap(first_start, first_end, second_start, second_end):
    first_start = aware_datetime(first_start)
    first_end = aware_datetime(first_end)
    second_start = aware_datetime(second_start)
    second_end = aware_datetime(second_end)
    return first_start < second_end and first_end > second_start


def transition_gap_minutes(first_start, first_end, second_start, second_end):
    first_start = aware_datetime(first_start)
    first_end = aware_datetime(first_end)
    second_start = aware_datetime(second_start)
    second_end = aware_datetime(second_end)
    if ranges_overlap(first_start, first_end, second_start, second_end):
        return None
    if first_end <= second_start:
        return int((second_start - first_end).total_seconds() // 60)
    return int((first_start - second_end).total_seconds() // 60)


def close_transition_warning(start, end, conflicts, threshold_minutes=TRANSITION_WARNING_MINUTES):
    close_gaps = [
        gap for gap in (
            transition_gap_minutes(start, end, conflict.starts_at, conflict.ends_at)
            for conflict in conflicts
            if conflict.source == "focus_block"
        )
        if gap is not None and 0 <= gap < threshold_minutes
    ]
    if not close_gaps:
        return ""
    gap = min(close_gaps)
    return f"This leaves only {gap} minutes between study blocks."


def subtract_conflict_from_window(window, conflict):
    if not ranges_overlap(window.starts_at, window.ends_at, conflict.starts_at, conflict.ends_at):
        return [window]
    pieces = []
    conflict_start = max(window.starts_at, aware_datetime(conflict.starts_at))
    conflict_end = min(window.ends_at, aware_datetime(conflict.ends_at))
    if window.starts_at < conflict_start:
        pieces.append(StudyWindow(window.starts_at, conflict_start, window.label))
    if conflict_end < window.ends_at:
        pieces.append(StudyWindow(conflict_end, window.ends_at, window.label))
    return [piece for piece in pieces if piece.duration_minutes >= MIN_BLOCK_MINUTES]


def subtract_conflicts(windows, conflicts):
    available = list(windows)
    for conflict in sorted(conflicts, key=lambda item: item.starts_at):
        next_available = []
        for window in available:
            next_available.extend(subtract_conflict_from_window(window, conflict))
        available = next_available
    return sorted(available, key=lambda item: item.starts_at)


def expand_weekly_availability(weekly_records, start_day, days=7):
    windows = []
    for offset in range(days):
        current_day = start_day + timedelta(days=offset)
        for record in weekly_records:
            if record.weekday == current_day.weekday():
                starts_at = combine(current_day, record.starts_at_time)
                ends_at = combine(current_day, record.ends_at_time)
                if ends_at > starts_at:
                    windows.append(StudyWindow(starts_at, ends_at, record.label))
    return sorted(windows, key=lambda item: item.starts_at)


def apply_availability_overrides(windows, override_records):
    additions = []
    blockers = []
    for record in override_records:
        starts_at = combine(record.date, record.starts_at_time)
        ends_at = combine(record.date, record.ends_at_time)
        if ends_at <= starts_at:
            continue
        if record.mode == "available":
            additions.append(StudyWindow(starts_at, ends_at, record.label))
        else:
            blockers.append(ScheduleConflict(starts_at, ends_at, record.label or "Unavailable", "calendar"))
    return subtract_conflicts(sorted([*windows, *additions], key=lambda item: item.starts_at), blockers)


def scheduled_block_conflicts(user_id, exclude_assignment_id=None):
    query = db.select(ScheduledFocusBlock).where(
        ScheduledFocusBlock.user_id == user_id,
        ScheduledFocusBlock.status.in_(SCHEDULED_BLOCK_STATUSES),
        ScheduledFocusBlock.starts_at.is_not(None),
        ScheduledFocusBlock.ends_at.is_not(None),
    )
    if exclude_assignment_id is not None:
        query = query.where(ScheduledFocusBlock.assignment_id != exclude_assignment_id)
    records = db.session.scalars(query).all()
    conflicts = []
    for record in records:
        assignment = db.session.get(Assignment, record.assignment_id)
        title = assignment.title if assignment else "Planned focus block"
        score = calculate_priority(assignment_priority_input(assignment)) if assignment else None
        conflicts.append(ScheduleConflict(
            aware_datetime(record.starts_at),
            aware_datetime(record.ends_at),
            title,
            "focus_block",
            assignment_id=record.assignment_id,
            focus_block_id=record.id,
            priority_score=score,
        ))
    return conflicts


def availability_windows_for_user(user_id, start_day=None, days=7):
    start_day = start_day or datetime.now(timezone.utc).date()
    end_day = start_day + timedelta(days=days - 1)
    weekly = db.session.scalars(
        db.select(WeeklyAvailability)
        .where(WeeklyAvailability.user_id == user_id)
        .order_by(WeeklyAvailability.weekday, WeeklyAvailability.starts_at_time)
    ).all()
    overrides = db.session.scalars(
        db.select(AvailabilityOverride)
        .where(
            AvailabilityOverride.user_id == user_id,
            AvailabilityOverride.date >= start_day,
            AvailabilityOverride.date <= end_day,
        )
        .order_by(AvailabilityOverride.date, AvailabilityOverride.starts_at_time)
    ).all()
    return apply_availability_overrides(expand_weekly_availability(weekly, start_day, days), overrides)


def recommendation_for_assignment(assignment, user, start_day=None, days=7, calendar_conflicts=None):
    requested = max(int(assignment.estimated_minutes or 0), 0)
    if requested <= 0:
        return ScheduleRecommendation(assignment.id, assignment.title, requested, 0, False, [], [])

    windows = availability_windows_for_user(user.id, start_day, days)
    focus_conflicts = scheduled_block_conflicts(user.id, exclude_assignment_id=assignment.id)
    hard_conflicts = list(calendar_conflicts or [])
    free_windows = subtract_conflicts(windows, [*hard_conflicts, *focus_conflicts])
    remaining = requested
    suggestions = []
    for window in free_windows:
        if remaining < MIN_BLOCK_MINUTES:
            break
        cursor = window.starts_at
        window_remaining = window.duration_minutes
        while remaining >= MIN_BLOCK_MINUTES and window_remaining >= MIN_BLOCK_MINUTES:
            block_minutes = min(remaining, MAX_BLOCK_MINUTES, window_remaining)
            if block_minutes < MIN_BLOCK_MINUTES:
                break
            starts_at = cursor
            ends_at = starts_at + timedelta(minutes=block_minutes)
            warning = close_transition_warning(starts_at, ends_at, focus_conflicts)
            suggestions.append(FocusBlockSuggestion(assignment.id, assignment.title, starts_at, ends_at, block_minutes, warning))
            remaining -= block_minutes
            cursor = ends_at
            window_remaining = int((window.ends_at - cursor).total_seconds() // 60)

    current_score = calculate_priority(assignment_priority_input(assignment), user.available_study_minutes)
    reschedule_conflicts = [
        conflict for conflict in focus_conflicts
        if conflict.priority_score is not None and current_score > conflict.priority_score and current_score - conflict.priority_score >= RESCHEDULE_SCORE_GAP
    ]
    scheduled = sum(item.planned_minutes for item in suggestions)
    return ScheduleRecommendation(
        assignment.id,
        assignment.title,
        requested,
        scheduled,
        scheduled < requested,
        suggestions,
        reschedule_conflicts,
    )


def window_contains(windows, starts_at, ends_at):
    starts_at = aware_datetime(starts_at)
    ends_at = aware_datetime(ends_at)
    return any(window.starts_at <= starts_at and window.ends_at >= ends_at for window in windows)


def validate_scheduled_block(assignment, user, starts_at, planned_minutes, confirm_transition=False):
    errors = []
    warnings = []
    if isinstance(planned_minutes, bool) or not isinstance(planned_minutes, int) or not 1 <= planned_minutes <= 240:
        errors.append("Focus duration must be a whole number from 1 to 240 minutes.")
        return None, errors, warnings, []
    starts_at = aware_datetime(starts_at)
    ends_at = starts_at + timedelta(minutes=planned_minutes)
    windows = availability_windows_for_user(user.id, starts_at.date(), 1)
    if not window_contains(windows, starts_at, ends_at):
        errors.append("Choose a time inside your availability that does not overlap class, work, or unavailable time.")

    focus_conflicts = [
        conflict for conflict in scheduled_block_conflicts(user.id, exclude_assignment_id=assignment.id)
        if ranges_overlap(starts_at, ends_at, conflict.starts_at, conflict.ends_at)
    ]
    if focus_conflicts:
        errors.append("This overlaps an existing study block. Choose combine, replace, reschedule existing, or keep your current plan.")

    all_focus_conflicts = scheduled_block_conflicts(user.id, exclude_assignment_id=assignment.id)
    warning = close_transition_warning(starts_at, ends_at, all_focus_conflicts)
    if warning and not confirm_transition:
        warnings.append(warning)
    return (starts_at, ends_at), errors, warnings, focus_conflicts


def parse_time(value):
    return time.fromisoformat(str(value))


def parse_date(value):
    return date.fromisoformat(str(value))
