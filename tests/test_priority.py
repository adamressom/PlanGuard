from datetime import datetime, timedelta, timezone

from planguard.services.priority import calculate_priority, rank_assignments

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

