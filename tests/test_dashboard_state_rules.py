from types import SimpleNamespace

from planguard.services.dashboard import dashboard_state


def state(active=None, completed=None, history=None, blocks=None, calendar=None, notion=None):
    return dashboard_state(
        active or [],
        completed or [],
        history or [],
        blocks or [],
        calendar or {"sync_status": "never"},
        notion,
    )


def test_first_time_requires_no_planning_history():
    assert state()["first_time"] is True
    assert state(completed=[object()])["first_time"] is False
    assert state(history=[object()])["first_time"] is False
    assert state(blocks=[object()])["first_time"] is False


def test_nothing_urgent_requires_active_non_overdue_low_priority_work():
    low = {"is_overdue": False, "priority_band": "low"}

    assert state(active=[low])["nothing_urgent"] is True
    assert state(active=[])["nothing_urgent"] is False
    assert state(active=[{**low, "is_overdue": True}])["nothing_urgent"] is False
    assert state(active=[{**low, "priority_band": "medium"}])["nothing_urgent"] is False


def test_loading_includes_calendar_or_notion_sync():
    assert state(calendar={"sync_status": "syncing"})["loading"] is True
    notion = SimpleNamespace(sync_status="syncing")
    assert state(notion=notion)["loading"] is True
    assert state()["loading"] is False


def test_calendar_fallback_and_error_are_mutually_explicit():
    cached = state(calendar={"sync_status": "cached"})
    error = state(calendar={"sync_status": "error"})

    assert cached["using_cached_calendar"] is True
    assert cached["calendar_error"] is False
    assert error["using_cached_calendar"] is False
    assert error["calendar_error"] is True
