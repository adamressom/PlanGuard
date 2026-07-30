from datetime import datetime, timedelta, timezone

from planguard import db
from planguard.models import IntegrationState


def test_empty_dashboard_has_actionable_empty_states(user_factory, sign_in):
    user_id = user_factory()
    client = sign_in(user_id)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"Your active queue is clear." in response.data
    assert b"Add your first assignment." in response.data
    assert b'href="/assignments/new"' in response.data
    assert b"Set availability" in response.data
    assert b"Completed assignments will move here." in response.data
    assert b"recent study history will appear here" in response.data
    assert b"Accepted focus blocks will appear here." in response.data


def test_dashboard_separates_overdue_and_completed_work(
    app,
    user_factory,
    assignment_factory,
    sign_in,
):
    user_id = user_factory()
    assignment_factory(
        user_id,
        title="Overdue lab",
        deadline=datetime.now(timezone.utc) - timedelta(days=2),
    )
    assignment_factory(
        user_id,
        title="Completed essay",
        progress=100,
        completed=True,
    )
    client = sign_in(user_id)

    response = client.get("/dashboard")
    active, completed = response.data.split(b'class="panel completed-queue"', 1)

    assert b"Overdue lab" in active
    assert b"overdue-task" in active
    assert b"due-badge overdue" in active
    assert b"Completed essay" not in active
    assert b"Completed essay" in completed


def test_dashboard_renders_syncing_as_loading_state(
    user_factory,
    integration_factory,
    sign_in,
):
    user_id = user_factory()
    integration_factory(user_id, sync_status="syncing")
    client = sign_in(user_id)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"Syncing" in response.data
    assert b"Syncing your latest data" in response.data
    assert b'aria-busy="true"' in response.data


def test_dashboard_renders_integration_error_with_recovery_action(
    app,
    user_factory,
    integration_factory,
    sign_in,
):
    user_id = user_factory()
    integration_id = integration_factory(
        user_id,
        sync_status="error",
        last_error_code="provider_unavailable",
    )
    client = sign_in(user_id)

    response = client.get("/dashboard")

    assert b"Google Calendar data could not be updated" in response.data
    assert b"Live and cached calendar data are unavailable." in response.data
    assert b"Review calendar status" in response.data
    assert b"Sync calendar" in response.data
    with app.app_context():
        integration = db.session.get(IntegrationState, integration_id)
        assert integration.last_error_code == "provider_unavailable"


def test_dashboard_explains_cached_fallback_is_active(
    user_factory,
    integration_factory,
    sign_in,
):
    user_id = user_factory()
    integration_factory(
        user_id,
        sync_status="cached",
        last_synced_at=datetime.now(timezone.utc) - timedelta(hours=1),
        last_error_code="provider_unavailable",
    )

    response = sign_in(user_id).get("/dashboard")

    assert b"Using cached data" in response.data
    assert b"Your plan is still protected." in response.data
    assert b"last successful sync" in response.data


def test_dashboard_shows_nothing_urgent_for_only_low_priority_work(
    user_factory,
    assignment_factory,
    sign_in,
):
    user_id = user_factory()
    assignment_factory(
        user_id,
        title="Reading for next month",
        deadline=datetime.now(timezone.utc) + timedelta(days=30),
        difficulty=1,
        course_weight=1,
        estimated_minutes=30,
        progress=60,
    )

    response = sign_in(user_id).get("/dashboard")

    assert b"Nothing urgent right now." in response.data
    assert b"currently low priority" in response.data
