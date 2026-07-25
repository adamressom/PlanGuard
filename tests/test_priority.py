from datetime import datetime, timedelta, timezone

from planguard.services.priority import calculate_priority, deadline_metadata, rank_assignments

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def task(**overrides):
    base = {"title": "Test", "deadline": NOW + timedelta(days=2), "difficulty": 3, "estimated_minutes": 60, "course_weight": 20, "progress": 0}
    return {**base, **overrides}


def test_priority_is_between_zero_and_one_hundred():
    assert 0 <= calculate_priority(task(), now=NOW) <= 100


def test_soon_deadline_scores_higher():
    soon = task(deadline=NOW + timedelta(hours=2))
    later = task(deadline=NOW + timedelta(days=6))
    assert calculate_priority(soon, now=NOW) > calculate_priority(later, now=NOW)


def test_higher_difficulty_scores_higher():
    assert calculate_priority(task(difficulty=5), now=NOW) > calculate_priority(task(difficulty=1), now=NOW)


def test_higher_course_weight_scores_higher():
    assert calculate_priority(task(course_weight=60), now=NOW) > calculate_priority(task(course_weight=5), now=NOW)


def test_progress_reduces_priority():
    assert calculate_priority(task(progress=0), now=NOW) > calculate_priority(task(progress=90), now=NOW)


def test_rank_assignments_descending():
    items = [task(title="Later", deadline=NOW + timedelta(days=6)), task(title="Soon", deadline=NOW + timedelta(hours=1))]
    ranked = rank_assignments(items, now=NOW)
    assert ranked[0]["title"] == "Soon"
    assert ranked[0]["priority_score"] >= ranked[1]["priority_score"]


def test_naive_deadline_is_supported():
    score = calculate_priority(task(deadline=datetime(2026, 1, 2)), now=NOW)
    assert isinstance(score, float)


def test_missing_and_malformed_values_do_not_crash_ranking():
    malformed = {"id": 1, "title": "Edge case", "deadline": None, "difficulty": None, "estimated_minutes": "unknown", "course_weight": float("nan"), "progress": "missing"}
    ranked = rank_assignments([malformed], available_minutes="invalid", now=NOW)
    assert 0 <= ranked[0]["priority_score"] <= 100
    assert ranked[0]["deadline_status"] == "missing"
    assert ranked[0]["due_label"] == "No deadline"


def test_overdue_assignment_gets_clear_metadata_and_bonus():
    overdue = task(deadline=NOW - timedelta(days=2))
    due_now = task(deadline=NOW)
    ranked = rank_assignments([due_now, overdue], now=NOW)
    assert ranked[0]["is_overdue"] is True
    assert ranked[0]["deadline_status"] == "overdue"
    assert ranked[0]["due_label"] == "Overdue by 2d"
    assert ranked[0]["priority_score"] > ranked[1]["priority_score"]


def test_equal_scores_use_deadline_then_id_as_deterministic_tiebreakers():
    later = task(id=2, title="Later", deadline=NOW + timedelta(days=11))
    earlier = task(id=3, title="Earlier", deadline=NOW + timedelta(days=10))
    same_deadline_lower_id = task(id=1, title="Lower ID", deadline=NOW + timedelta(days=10))
    ranked = rank_assignments([later, earlier, same_deadline_lower_id], now=NOW)
    assert len({item["priority_score"] for item in ranked}) == 1
    assert [item["id"] for item in ranked] == [1, 3, 2]


def test_deadline_metadata_handles_near_deadline_without_rounding_to_zero():
    metadata = deadline_metadata(NOW + timedelta(minutes=20), NOW)
    assert metadata["due_label"] == "Due in less than 1 hour"
