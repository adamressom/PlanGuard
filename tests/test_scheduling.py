from datetime import date, datetime, time, timedelta, timezone

import pytest

from planguard import create_app, db
from planguard.models import Assignment, AvailabilityOverride, ScheduledFocusBlock, User, WeeklyAvailability
from planguard.services.scheduling import availability_windows_for_user, recommendation_for_assignment, ranges_overlap, validate_scheduled_block


@pytest.fixture
def scheduling_setup(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "scheduling-secret", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'scheduling.db'}"})
    with app.app_context():
        owner = User(email="owner@example.com", display_name="Owner", available_study_minutes=120)
        owner.set_password("owner-password")
        other = User(email="other@example.com", display_name="Other")
        other.set_password("other-password")
        db.session.add_all([owner, other])
        db.session.flush()
        assignment = Assignment(
            user_id=owner.id,
            title="Research paper",
            course="ENG 301",
            deadline=datetime(2026, 8, 10, 17, 0, tzinfo=timezone.utc),
            difficulty=5,
            estimated_minutes=150,
            course_weight=40,
            progress=0,
        )
        lower = Assignment(
            user_id=owner.id,
            title="Reading notes",
            course="HIST 101",
            deadline=datetime(2026, 8, 20, 17, 0, tzinfo=timezone.utc),
            difficulty=1,
            estimated_minutes=30,
            course_weight=5,
            progress=0,
        )
        db.session.add_all([assignment, lower])
        db.session.commit()
        ids = {"owner": owner.id, "other": other.id, "assignment": assignment.id, "lower": lower.id}
    return app, ids


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def add_monday_availability(user_id):
    db.session.add(WeeklyAvailability(
        user_id=user_id,
        weekday=0,
        starts_at_time=time(9, 0),
        ends_at_time=time(12, 0),
        label="Morning study",
    ))
    db.session.commit()


def test_overlap_detection_allows_touching_edges():
    first_start = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
    first_end = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
    assert ranges_overlap(first_start, first_end, datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc), datetime(2026, 8, 3, 10, 30, tzinfo=timezone.utc))
    assert not ranges_overlap(first_start, first_end, datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc), datetime(2026, 8, 3, 11, 0, tzinfo=timezone.utc))


def test_weekly_availability_and_unavailable_override_create_real_windows(scheduling_setup):
    app, ids = scheduling_setup
    with app.app_context():
        add_monday_availability(ids["owner"])
        db.session.add(AvailabilityOverride(
            user_id=ids["owner"],
            date=date(2026, 8, 3),
            starts_at_time=time(10, 0),
            ends_at_time=time(11, 0),
            mode="unavailable",
            label="Class",
        ))
        db.session.commit()
        windows = availability_windows_for_user(ids["owner"], date(2026, 8, 3), 1)
        assert [(item.starts_at.time(), item.ends_at.time()) for item in windows] == [(time(9, 0), time(10, 0)), (time(11, 0), time(12, 0))]


def test_recommendation_splits_large_assignment_across_available_windows(scheduling_setup):
    app, ids = scheduling_setup
    with app.app_context():
        add_monday_availability(ids["owner"])
        assignment = db.session.get(Assignment, ids["assignment"])
        recommendation = recommendation_for_assignment(assignment, db.session.get(User, ids["owner"]), start_day=date(2026, 8, 3), days=1)
        assert recommendation.requested_minutes == 150
        assert recommendation.scheduled_minutes == 150
        assert [item.planned_minutes for item in recommendation.suggestions] == [90, 60]
        assert recommendation.is_partial is False


def test_close_transition_is_warning_not_hard_conflict(scheduling_setup):
    app, ids = scheduling_setup
    with app.app_context():
        add_monday_availability(ids["owner"])
        db.session.add(ScheduledFocusBlock(
            user_id=ids["owner"],
            assignment_id=ids["lower"],
            starts_at=datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 8, 3, 10, 30, tzinfo=timezone.utc),
            planned_minutes=30,
            status="scheduled",
        ))
        db.session.commit()
        assignment = db.session.get(Assignment, ids["assignment"])
        block_range, errors, warnings, focus_conflicts = validate_scheduled_block(
            assignment,
            db.session.get(User, ids["owner"]),
            datetime(2026, 8, 3, 10, 40, tzinfo=timezone.utc),
            30,
        )
        assert block_range is not None
        assert errors == []
        assert focus_conflicts == []
        assert warnings == ["This leaves only 10 minutes between study blocks."]


def test_availability_page_and_creation_redirect_to_schedule(scheduling_setup):
    app, ids = scheduling_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    assert client.get("/availability").status_code == 200
    added = client.post("/availability/weekly", data={"weekday": "0", "starts_at_time": "09:00", "ends_at_time": "12:00", "label": "Morning"})
    assert added.status_code == 302
    created = client.post("/assignments/new", data={
        "title": "Lab report",
        "course": "BIO 201",
        "deadline": "2026-08-08T17:00",
        "difficulty": "4",
        "estimated_minutes": "60",
        "course_impact": "20",
        "progress": "0",
    })
    assert created.status_code == 302
    assert "/schedule" in created.headers["Location"]


def test_accepting_and_dismissing_suggestions_are_persisted(scheduling_setup):
    app, ids = scheduling_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    with app.app_context():
        add_monday_availability(ids["owner"])
    accepted = client.post(f"/assignments/{ids['assignment']}/schedule", data={
        "action": "adjust",
        "starts_at": "2026-08-03T09:00",
        "planned_minutes": "45",
    })
    assert accepted.status_code == 302
    with app.app_context():
        block = db.session.scalar(db.select(ScheduledFocusBlock).where(ScheduledFocusBlock.status == "scheduled"))
        assert block.assignment_id == ids["assignment"]
        assert block.planned_minutes == 45
    dashboard = client.get("/dashboard")
    assert b"Planned focus" in dashboard.data
    assert b"Research paper" in dashboard.data

    dismissed = client.post(f"/assignments/{ids['lower']}/schedule", data={"action": "dismiss"})
    assert dismissed.status_code == 302
    with app.app_context():
        assert db.session.scalar(
            db.select(ScheduledFocusBlock).where(
                ScheduledFocusBlock.assignment_id == ids["lower"],
                ScheduledFocusBlock.status == "dismissed",
            )
        )
    remembered = client.get(f"/assignments/{ids['lower']}/schedule")
    assert b"Suggestions dismissed" in remembered.data


def test_focus_block_conflict_can_be_replaced_by_user_choice(scheduling_setup):
    app, ids = scheduling_setup
    client = app.test_client()
    sign_in(client, ids["owner"])
    with app.app_context():
        add_monday_availability(ids["owner"])
        db.session.add(ScheduledFocusBlock(
            user_id=ids["owner"],
            assignment_id=ids["lower"],
            starts_at=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc),
            planned_minutes=30,
            status="scheduled",
        ))
        db.session.commit()

    conflict = client.post(f"/assignments/{ids['assignment']}/schedule", data={
        "action": "adjust",
        "starts_at": "2026-08-03T09:15",
        "planned_minutes": "45",
    })
    assert conflict.status_code == 409
    assert b"Combine" in conflict.data
    assert b"Replace" in conflict.data
    assert b"Reschedule existing" in conflict.data

    replaced = client.post(f"/assignments/{ids['assignment']}/schedule", data={
        "action": "adjust",
        "starts_at": "2026-08-03T09:15",
        "planned_minutes": "45",
        "conflict_resolution": "replace_existing",
    })
    assert replaced.status_code == 302
    with app.app_context():
        blocks = db.session.scalars(db.select(ScheduledFocusBlock).order_by(ScheduledFocusBlock.id)).all()
        assert [block.status for block in blocks] == ["cancelled", "scheduled"]
        assert blocks[-1].assignment_id == ids["assignment"]
        assert blocks[-1].source == "replacement"
