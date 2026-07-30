def dashboard_state(
    active_assignments,
    completed_assignments,
    focus_history,
    upcoming_blocks,
    calendar_status,
    notion_integration=None,
):
    """Return deterministic presentation flags for the dashboard."""
    first_time = not any((
        active_assignments,
        completed_assignments,
        focus_history,
        upcoming_blocks,
    ))
    nothing_urgent = bool(active_assignments) and all(
        not assignment.get("is_overdue")
        and assignment.get("priority_band") == "low"
        for assignment in active_assignments
    )
    notion_sync_status = (
        notion_integration.sync_status if notion_integration is not None else "never"
    )
    calendar_sync_status = (
        calendar_status.get("sync_status", "never")
        if isinstance(calendar_status, dict)
        else getattr(calendar_status, "sync_status", "never")
    )
    return {
        "first_time": first_time,
        "nothing_urgent": nothing_urgent,
        "loading": "syncing" in {calendar_sync_status, notion_sync_status},
        "using_cached_calendar": calendar_sync_status == "cached",
        "calendar_error": calendar_sync_status == "error",
    }
