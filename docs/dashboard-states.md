# Dashboard state rules

Dashboard feedback is derived from saved user data and integration status. The
rules are deterministic and can appear alongside the usable parts of the
dashboard:

- **First-time onboarding:** no active or completed assignments, focus history,
  or scheduled focus blocks. Show direct actions to add an assignment and set
  availability.
- **Empty active queue:** no active assignments. Keep completed work visible and
  provide an Add assignment action inside the empty state.
- **Loading:** Google Calendar or Notion has `sync_status=syncing`. Mark the
  update as busy and explain that the saved plan remains usable.
- **Using cached data:** Google Calendar live sync failed but a usable cache is
  active. Explicitly say that cached conflicts are still protecting suggestions.
- **Calendar error:** neither live nor cached Google Calendar data is usable.
  Explain that suggested times need review and link to retry/reconnect controls.
- **Overdue:** an active assignment deadline has passed. Keep the overdue badge
  and visual treatment on its assignment row.
- **Completed:** completed assignments are excluded from the active queue and
  shown in Finished work.
- **Nothing urgent:** at least one active assignment exists, none is overdue, and
  every active assignment is in the low-priority band.

Loading and integration warnings do not replace assignment content. Students can
continue using their saved plan while an integration updates or recovers.
